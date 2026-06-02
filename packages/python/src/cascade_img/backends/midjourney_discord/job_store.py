"""Persistent job store for the bridge daemon.

The bridge keeps jobs in an in-memory ``OrderedDict`` for speed and for the
resilience layer's concurrency discipline. That dict is the working store; this
module adds durability *beside* it: a write-through SQLite sidecar so a daemon
restart can resume tracking in-flight jobs instead of dropping them (the
biggest production footnote at v0.1).

Design choices that keep it correct:

* **Decoupled from ``Job``.** The store reads and writes plain row dicts
  (``dataclasses.asdict(job)`` shape). The bridge converts ``Job`` <-> dict at
  the boundary, so this module has no import cycle and is unit-testable with
  plain dicts.
* **Thread-safe.** The bridge persists from both the Discord thread and Flask
  worker threads, so the connection is opened ``check_same_thread=False`` and
  every statement runs under an internal lock.
* **Status column for cheap rehydration.** Each row carries its ``status`` in
  a dedicated column so "load the non-terminal jobs" is one indexed query, not
  a full-table JSON scan.
* **``:memory:`` opt-out.** Passing ``":memory:"`` gives an ephemeral store
  (tests, or an operator who wants the pre-Wave-G behavior back).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("cascade_img.job_store")

# Statuses that are terminal — excluded from rehydration. Kept as bare strings
# so this module needn't import the bridge's Status enum (avoids a cycle).
_TERMINAL = ("done", "failed")


class JobStore:
    """SQLite-backed durable mirror of the in-memory job map."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        # check_same_thread=False: the bridge writes from multiple threads. We
        # serialize every access with our own lock, so this is safe.
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._lock = threading.Lock()
        with self._lock:
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS jobs (
                    job_id     TEXT PRIMARY KEY,
                    status     TEXT NOT NULL,
                    updated_at REAL NOT NULL,
                    data       TEXT NOT NULL
                )
                """
            )
            self._conn.commit()

    @property
    def mode(self) -> str:
        return "memory" if self.path == ":memory:" else "sqlite"

    def put(self, row: dict[str, Any]) -> None:
        """Upsert a job row (the ``asdict(job)`` form). ``status`` may be an
        enum or a string; it is stored as its string value."""
        job_id = row["job_id"]
        # row["status"] may be a Status(str, Enum) member or a plain string.
        # ``str(enum_member)`` yields "Status.DONE" (Enum.__str__), which would
        # break the terminal-status filter — take the enum's ``.value`` if present.
        status = getattr(row["status"], "value", row["status"])
        updated_at = float(row.get("updated_at") or 0.0)
        data = json.dumps(row, default=str)
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO jobs (job_id, status, updated_at, data) "
                "VALUES (?, ?, ?, ?)",
                (job_id, status, updated_at, data),
            )
            self._conn.commit()

    def delete(self, job_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM jobs WHERE job_id = ?", (job_id,))
            self._conn.commit()

    def load_nonterminal(self) -> list[dict[str, Any]]:
        """Return every non-terminal job row, oldest-updated first (so the
        bridge can rebuild PENDING_GRID in a sensible order)."""
        placeholders = ", ".join("?" for _ in _TERMINAL)
        with self._lock:
            cur = self._conn.execute(
                f"SELECT data FROM jobs WHERE status NOT IN ({placeholders}) ORDER BY updated_at",
                _TERMINAL,
            )
            rows = cur.fetchall()
        # Decode per-row: one corrupt/truncated `data` blob (e.g. a torn write on
        # an earlier crash) must drop only that job, not abort the whole
        # rehydration and crash daemon startup. Skip-and-log the bad row.
        out: list[dict[str, Any]] = []
        for r in rows:
            try:
                out.append(json.loads(r[0]))
            except (ValueError, TypeError) as e:
                log.warning(f"job-store: skipping unparseable row during rehydration: {e}")
        return out

    def count(self) -> int:
        with self._lock:
            return int(self._conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()

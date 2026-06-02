"""SDD emit/snapshot — Python port of the reference pattern.

Every load-bearing state transition in the daemon and the orchestration layer
calls :func:`emit`. A grader reads :func:`snapshot` and asserts against the
locked vocabulary at ``cascade_img/signals/versions/0.1.json``. The program
speaks; the grader listens. The parity tool catches drift between code and
vocabulary; emit itself never crashes the daemon over a vocabulary mismatch.

The buffer is process-global, lock-protected, and bounded only by memory —
for the daemon's lifetime that's fine, but graders periodically
:func:`flush_to_file` and :func:`clear` between runs.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from threading import Lock
from typing import Any

VOCAB_VERSION = "0.1"

_BUFFER: list[dict[str, Any]] = []
_LOCK = Lock()


def emit(tag: str, **payload: Any) -> dict[str, Any]:
    """Append a signal record to the in-process buffer and return it.

    Records are dicts with stable shape:
        {ts: float, tag: str, vocab_version: str, payload: dict}
    """
    record = {
        "ts": time.time(),
        "tag": tag,
        "vocab_version": VOCAB_VERSION,
        "payload": dict(payload),
    }
    with _LOCK:
        _BUFFER.append(record)
    return record


def snapshot() -> list[dict[str, Any]]:
    """Return a copy of the current buffer. Cheap; safe to call from any thread."""
    with _LOCK:
        return list(_BUFFER)


def clear() -> None:
    """Wipe the buffer. For tests and graders between runs; never call at runtime."""
    with _LOCK:
        _BUFFER.clear()


def flush_to_file(path: Path) -> int:
    """Write the buffer to a JSONL file, return line count. Does not clear."""
    lines = snapshot()
    path.write_text(
        "\n".join(json.dumps(r) for r in lines) + ("\n" if lines else ""),
        encoding="utf-8",
    )
    return len(lines)

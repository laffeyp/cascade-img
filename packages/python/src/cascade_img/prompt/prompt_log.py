"""PromptLog — the append-only prompt log that's also the agent's working memory.

This is the *prompt log*: a per-run record of what was tried for each asset
(prompt, outputs, agent decision). It is distinct from the bridge's *job store*
(``backends/midjourney_discord/job_store.py``), which durably mirrors in-flight
Discord jobs so the daemon can resume after a restart. The prompt log is the
caller's memory across attempts; the job store is the daemon's memory across
restarts.

Records go to disk as JSON Lines (one record per line, structured, trivially
parseable by an LLM via :meth:`read`). A separate :meth:`render_markdown`
helper produces the human-readable markdown form on demand. The JSONL is the
canonical store; the markdown is a render of it.

Each record:

    {
      "ts": "2026-06-02T03:04:05Z",
      "asset_id": "mountain-icon",
      "prompt": "...",
      "backend": "midjourney_discord",
      "job_id": "...",
      "upscale": "1" | "all" | null,
      "outputs": { "image_path": "...", "grid_path": "...", "upscale_paths": {...} },
      "error": null | "...",
      "agent_decision": "promote" | "regenerate" | "escalate" | null,
      "agent_reason": "..." | null
    }

The agent's loop reads :meth:`read` to answer "what have I tried for this
asset already?" without scraping prose.
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock
from typing import Any

from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.prompt_log")


class AgentDecision(StrEnum):
    """The closed set of decisions an LLM operator may record on a generation run.

    Enforced at append time so the prompt log doesn't accumulate freeform
    nonsense an operator can't grep for. Operators that need a state outside
    these four should escalate to the human or surface a vocabulary proposal.
    """

    PROMOTE = "promote"
    REGENERATE = "regenerate"
    ESCALATE = "escalate"
    DRY_RUN = "dry_run"


class PromptLog:
    """Append-only JSONL log of every generation run. Thread-safe."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(
        self,
        asset_id: str,
        prompt: str,
        backend: str,
        job_id: str | None = None,
        upscale: str | None = None,
        outputs: dict[str, Any] | None = None,
        error: str | None = None,
        agent_decision: AgentDecision | str | None = None,
        agent_reason: str | None = None,
    ) -> dict[str, Any]:
        """Append one record. Returns the record dict.

        ``agent_decision`` is validated against :class:`AgentDecision`. Strings
        are accepted and coerced; values not in the enum raise ``ValueError``
        with the allowed set named in the message.
        """
        if agent_decision is not None and not isinstance(agent_decision, AgentDecision):
            try:
                agent_decision = AgentDecision(agent_decision)
            except ValueError as e:
                allowed = [d.value for d in AgentDecision]
                raise ValueError(
                    f"agent_decision must be one of {allowed}, got {agent_decision!r}"
                ) from e
        decision_value = agent_decision.value if isinstance(agent_decision, AgentDecision) else None

        record: dict[str, Any] = {
            "ts": datetime.now(UTC).isoformat(),
            "asset_id": asset_id,
            "prompt": prompt,
            "backend": backend,
            "job_id": job_id,
            "upscale": upscale,
            "outputs": outputs or {},
            "error": error,
            "agent_decision": decision_value,
            "agent_reason": agent_reason,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock, self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        emit(
            "PROMPT_LOGGED",
            asset_id=asset_id,
            has_job_id=bool(job_id),
            has_error=bool(error),
            agent_decision=decision_value or "",
        )
        return record

    def read(self, n: int | None = None) -> list[dict[str, Any]]:
        """Read records back as structured dicts.

        Args:
            n: If set, return the last n records (chronologically). If None,
               return all records.
        """
        # Read under lock with EAFP — catches the TOCTOU race where the file
        # exists at exists() time but is deleted before read_text() (review-
        # flagged 2026-06-02). A missing file is the same as no records.
        with self._lock:
            try:
                lines = self.path.read_text(encoding="utf-8").splitlines()
            except FileNotFoundError:
                return []
        # Skip-and-continue per line. A single torn or hand-edited line must not
        # abort the whole read: this log IS the agent's working memory across
        # loop iterations, and losing every record to one corrupt line is the
        # larger failure. The bad line is logged (not silently dropped) so the
        # corruption is observable, and the surviving records are returned.
        records: list[dict[str, Any]] = []
        for line in lines:
            if not line.strip():
                continue
            try:
                records.append(json.loads(line))
            except (json.JSONDecodeError, ValueError) as e:
                log.warning("skipping unparseable prompt-log line in %s: %s", self.path, e)
        if n is not None:
            # records[-0:] is the whole list, not none of it — guard n=0.
            return records[-n:] if n > 0 else []
        return records

    def render_markdown(self) -> str:
        """Render the full log as human-readable markdown. Useful for
        ``cat``-ing in a terminal or pasting into a review.

        Reads every field defensively (``.get`` with defaults) so a
        schema-incomplete record — a hand-edited or older-schema line that
        :meth:`read` deliberately tolerates — degrades to placeholders instead of
        aborting the whole render with a ``KeyError``. (``read`` is hand-edit
        tolerant; this keeps the renderer consistent with it.)"""
        records = self.read()
        if not records:
            return ""
        chunks: list[str] = ["# Prompt log\n", "*Append-only. One block per generation run.*\n"]
        for r in records:
            chunks.append(
                f"\n## {r.get('ts', '?')} — {r.get('asset_id', '?')} "
                f"(upscale={r.get('upscale') or 'grid'})\n"
            )
            chunks.append("\nPrompt:\n```\n" + (r.get("prompt") or "") + "\n```\n")
            if r.get("job_id"):
                chunks.append(f"\nJob: `{r['job_id']}` — backend={r.get('backend') or 'unknown'}\n")
            outputs = r.get("outputs") or {}
            for k, v in outputs.items():
                chunks.append(f"{k.title()}: `{v}`\n")
            if r.get("error"):
                chunks.append(f"Error: {r['error']}\n")
            if r.get("agent_decision"):
                chunks.append(
                    f"\nAgent decision: **{r['agent_decision']}** — {r.get('agent_reason') or ''}\n"
                )
            chunks.append("\n---\n")
        return "".join(chunks)

"""PromptLog — append-only ledger that's also the agent's working memory.

Records go to disk as JSON Lines (one record per line, structured, trivially
parseable by an LLM via :meth:`read`). A separate :meth:`render_markdown`
helper produces the human-readable markdown form on demand. The JSONL is the
canonical store; the markdown is a render of it.

Each record:

    {
      "ts": "2026-06-02T03:04:05Z",
      "asset_id": "bird",
      "prompt": "...",
      "backend": "midjourney_discord",
      "job_id": "...",
      "upscale": "1" | "all" | null,
      "outputs": { "image_path": "...", "grid_path": "...", "upscales": {...} },
      "error": null | "...",
      "agent_decision": "promote" | "reroll" | "escalate" | null,
      "agent_reason": "..." | null
    }

The agent's loop reads :meth:`read` to answer "what have I tried for this
asset already?" without scraping prose.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any, Optional, Union

from cascade_img.instrumentation.sdd import emit


class PromptLog:
    """Append-only JSONL log of every roll. Thread-safe."""

    def __init__(self, path: Union[str, Path]) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = Lock()

    def append(
        self,
        asset_id: str,
        prompt: str,
        backend: str,
        job_id: Optional[str] = None,
        upscale: Optional[str] = None,
        outputs: Optional[dict[str, Any]] = None,
        error: Optional[str] = None,
        agent_decision: Optional[str] = None,
        agent_reason: Optional[str] = None,
    ) -> dict[str, Any]:
        """Append one record. Returns the record dict."""
        record: dict[str, Any] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "asset_id": asset_id,
            "prompt": prompt,
            "backend": backend,
            "job_id": job_id,
            "upscale": upscale,
            "outputs": outputs or {},
            "error": error,
            "agent_decision": agent_decision,
            "agent_reason": agent_reason,
        }
        line = json.dumps(record, ensure_ascii=False)
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f:
                f.write(line + "\n")
        emit(
            "PROMPT_LOGGED",
            asset_id=asset_id,
            has_job_id=bool(job_id),
            has_error=bool(error),
            agent_decision=agent_decision or "",
        )
        return record

    def read(self, n: Optional[int] = None) -> list[dict[str, Any]]:
        """Read records back as structured dicts.

        Args:
            n: If set, return the last n records (chronologically). If None,
               return all records.
        """
        if not self.path.exists():
            return []
        with self._lock:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        records = [json.loads(l) for l in lines if l.strip()]
        if n is not None:
            return records[-n:]
        return records

    def render_markdown(self) -> str:
        """Render the full log as the markdown shape Katybird's runbook
        produces. Useful for ``cat``-ing in a terminal or pasting into a
        review."""
        records = self.read()
        if not records:
            return ""
        chunks: list[str] = ["# Prompt log\n", "*Append-only. One block per roll.*\n"]
        for r in records:
            chunks.append(
                f"\n## {r['ts']} — {r['asset_id']} (upscale={r.get('upscale') or 'grid'})\n"
            )
            chunks.append("\nPrompt:\n```\n" + r["prompt"] + "\n```\n")
            if r.get("job_id"):
                chunks.append(f"\nJob: `{r['job_id']}` — backend={r['backend']}\n")
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

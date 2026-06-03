"""MCP tools for the prompt log — the agent's working memory across iterations."""

from __future__ import annotations

from typing import Any

from cascade_img.interfaces.mcp import _envelope


async def log_append(
    asset_id: str,
    prompt: str,
    backend: str = "midjourney_discord",
    job_id: str | None = None,
    upscale: str | None = None,
    outputs: dict[str, Any] | None = None,
    error: str | None = None,
    agent_decision: str | None = None,
    agent_reason: str | None = None,
) -> dict[str, Any]:
    """Append a record to the prompt log.

    ``agent_decision`` must be one of: ``"promote"``, ``"reroll"``,
    ``"escalate"``, ``"dry_run"`` (or omitted). Invalid values produce a
    structured ValueError via the ``_run_tool`` envelope, naming the allowed
    set in the message.
    """

    def go():
        record = _envelope._log.append(
            asset_id=asset_id,
            prompt=prompt,
            backend=backend,
            job_id=job_id,
            upscale=upscale,
            outputs=outputs,
            error=error,
            agent_decision=agent_decision,
            agent_reason=agent_reason,
        )
        return {"record": record}

    return await _envelope._run_tool("log_append", go)


async def read_prompt_log(n: int | None = None) -> dict[str, Any]:
    """Read the prompt log back as structured records. ``n`` returns the
    last n entries; omit for all. This is the agent's working memory across
    loop iterations — the answer to 'what have I tried for this asset?'"""

    def go():
        return {"records": _envelope._log.read(n=n)}

    return await _envelope._run_tool("read_prompt_log", go)

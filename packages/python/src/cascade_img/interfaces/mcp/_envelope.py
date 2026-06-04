"""Shared wiring for the MCP tools: the response envelope + long-lived state.

Every tool funnels through :func:`_run_tool`, which emits ``MCP_TOOL_CALLED``
before and ``MCP_TOOL_COMPLETED`` / ``MCP_TOOL_FAILED`` after, and turns any
exception into the structured ``{ok: false, error: {code, message,
remediation?}}`` envelope. Sync callables are dispatched on a worker thread so
concurrent tool calls don't block the asyncio loop.

The long-lived singletons (``_backend``, ``_composer``, ``_log``) live here, in
one place, so the tool modules and the tests both reference them through this
module — patching ``_envelope._backend`` in a test reroutes every tool that
reads it. Defaults come from the environment at import; tools may override
per call.
"""

from __future__ import annotations

import asyncio
import inspect
import os
import time
from pathlib import Path
from typing import Any

from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend
from cascade_img.prompt.composer import PromptComposer
from cascade_img.prompt.prompt_log import PromptLog
from cascade_img.vocabulary import emit

CASCADE_BRIDGE_URL = os.environ.get("CASCADE_BRIDGE_URL", "http://127.0.0.1:5000")
CASCADE_PROMPT_LOG = Path(
    os.environ.get("CASCADE_PROMPT_LOG", "./cascade-prompt-log.jsonl")
).resolve()

_backend = MidjourneyDiscordBackend(base_url=CASCADE_BRIDGE_URL)
_composer = PromptComposer()
_log = PromptLog(CASCADE_PROMPT_LOG)


def _is_coro(fn) -> bool:
    return inspect.iscoroutinefunction(fn)


async def _run_tool(name: str, fn, **kwargs) -> dict[str, Any]:
    emit("MCP_TOOL_CALLED", tool=name)
    t0 = time.time()
    try:
        if _is_coro(fn):
            result = await fn(**kwargs)
        else:
            # Sync callable: run on a worker thread so the asyncio loop stays
            # responsive while concurrent tool calls execute.
            result = await asyncio.to_thread(lambda: fn(**kwargs))
        emit(
            "MCP_TOOL_COMPLETED",
            tool=name,
            duration_ms=int((time.time() - t0) * 1000),
        )
        return {"ok": True, "result": result}
    except Exception as e:
        code = getattr(e, "code", type(e).__name__)
        emit("MCP_TOOL_FAILED", tool=name, error_code=code, error_message=str(e))
        payload: dict[str, Any] = {
            "ok": False,
            "error": {
                "code": code,
                "message": str(e),
            },
        }
        # MissingEnvError-style structured errors carry remediation
        remediation = getattr(e, "remediation", None)
        if remediation:
            payload["error"]["remediation"] = remediation
        return payload

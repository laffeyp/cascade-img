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

# --- read-first gate -------------------------------------------------------
# cascade-img is operated by an LLM agent whose competence is whatever is in its
# context. Until ``cascade_guide`` has been called this session (which injects
# the full operating manual), the tools that compose/generate/curate refuse with
# a structured GUIDE_UNREAD error rather than acting on an unread operator. The
# read-only orientation tools stay open so the agent can find its footing. State
# is per-MCP-server-process (this module's lifetime = the agent's session); set
# by a successful ``cascade_guide`` call via ``_envelope._guide_read = True``.
_guide_read = False

_GATED_TOOLS = frozenset(
    {
        "compose_prompt",
        "compose_video",
        "imagine",
        "generate_video",
        "mj_action",
        "crop_grid",
        "alpha_key",
        "promote",
        "contact_sheet",
        "auto_trim",
        "palette_quantize",
        "sprite_sheet",
        "score_grid",
        "video_filmstrip",
        "loop_seam_delta",
        "log_append",
    }
)
# Exempt (always allowed, guide unread): cascade_guide, bridge_health, status,
# wait, read_prompt_log — orientation/inspection, safe before the manual is read.


class GuideUnreadError(Exception):
    """A gated tool was called before ``cascade_guide`` was read this session.

    Carries ``code``/``remediation`` so ``_run_tool`` renders the structured
    ``{ok: false, error: {code, message, remediation}}`` envelope (the same shape
    as ``MissingEnvError``)."""

    code = "GUIDE_UNREAD"
    remediation = (
        "Call cascade_guide first — it returns the full operating manual (the "
        "loop, every tool, the failure-to-action table). The generation and "
        "curation tools are gated until it is read this session."
    )

    def __init__(self) -> None:
        super().__init__("operating manual not yet read this session; call cascade_guide first")


def _require_guide(name: str) -> None:
    """Raise :class:`GuideUnreadError` if ``name`` is gated and the guide is unread."""
    if name in _GATED_TOOLS and not _guide_read:
        raise GuideUnreadError()


def _is_coro(fn) -> bool:
    return inspect.iscoroutinefunction(fn)


async def _run_tool(name: str, fn, **kwargs) -> dict[str, Any]:
    emit("MCP_TOOL_CALLED", tool=name)
    t0 = time.time()
    try:
        # Read-first gate: a gated tool called before cascade_guide raises here,
        # inside the try, so the CALLED->FAILED pairing holds and the work (the
        # backend call) never runs.
        _require_guide(name)
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
    except asyncio.CancelledError:
        # CancelledError is a BaseException, so the broad `except Exception`
        # below does NOT catch it: without this clause a cancelled tool call
        # leaves MCP_TOOL_CALLED unpaired (breaking the pairing invariant) and
        # swallows the cancellation. Emit the terminal FAILED tag to close the
        # pair, then re-raise so the cancel propagates (a swallowed cancel would
        # wedge the asyncio task that requested it). Note: a sync tool already
        # dispatched on the worker thread keeps running to completion — Python
        # can't cancel a live thread — so a cancel mid-`imagine` can still let
        # the underlying POST land. Closing that double-submit window needs
        # idempotency at the /imagine write boundary (surfaced separately).
        emit(
            "MCP_TOOL_FAILED",
            tool=name,
            error_code="CANCELLED",
            error_message="tool call cancelled",
        )
        raise
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

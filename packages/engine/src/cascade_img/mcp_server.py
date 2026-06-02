"""MCP server — the primary agent-facing surface for cascade-img.

Exposes the composer, backend, curation, and prompt-log as MCP tools that an
agent host (Claude Desktop, Cursor, Cline, Continue, custom frameworks) can
invoke directly. Every tool returns a structured dict; agents parse the shape
without scraping prose.

Start it with the ``cascade-mj-mcp`` console script. Stdio transport by
default — the convention for Claude Desktop and Cursor. Pass ``--http <port>``
to run HTTP transport instead.

Every tool call emits ``MCP_TOOL_CALLED`` (before) and ``MCP_TOOL_COMPLETED``
or ``MCP_TOOL_FAILED`` (after). The locked vocabulary in
``signals/versions/0.1.json`` is the contract.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend
from cascade_img.composer import (
    IdentityStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.curation import (
    DEFAULT_TOLERANCE,
    alpha_key_corners,
    crop_quadrant,
    promote as curation_promote,
)
from cascade_img.instrumentation.runtime import emit
from cascade_img.log import PromptLog


# ---------------------------------------------------------------------------
# Module-level state
# ---------------------------------------------------------------------------
#
# The MCP server is a long-running process. It holds a backend handle (bridge
# URL), a composer, and a path to the prompt log. Defaults come from env at
# startup; tools may override per-call.

CASCADE_BRIDGE_URL = os.environ.get("CASCADE_BRIDGE_URL", "http://127.0.0.1:5000")
CASCADE_PROMPT_LOG = Path(
    os.environ.get("CASCADE_PROMPT_LOG", "./cascade-prompt-log.jsonl")
).resolve()

_backend = MidjourneyDiscordBackend(base_url=CASCADE_BRIDGE_URL)
_composer = PromptComposer()
_log = PromptLog(CASCADE_PROMPT_LOG)

mcp = FastMCP("cascade-mj")


# ---------------------------------------------------------------------------
# Tool envelope: emit before/after, capture exceptions as structured errors
# ---------------------------------------------------------------------------


async def _run_tool(name: str, fn, **kwargs) -> dict[str, Any]:
    emit("MCP_TOOL_CALLED", tool=name)
    t0 = time.time()
    try:
        if _is_coro(fn):
            result = await fn(**kwargs)
        else:
            # Sync callable — run on a worker thread so the asyncio loop
            # stays responsive for concurrent tool calls. Matches the
            # backend's synchronous-by-design contract (Sprint 008).
            import asyncio as _asyncio
            result = await _asyncio.to_thread(lambda: fn(**kwargs))
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


def _is_coro(fn) -> bool:
    import asyncio
    return asyncio.iscoroutinefunction(fn)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@mcp.tool()
async def compose_prompt(
    subject: str,
    constraints: Optional[list[str]] = None,
    moodboard: Optional[str] = None,
    sref: Optional[str] = None,
    stylize: Optional[int] = None,
    style_raw: bool = True,
    oref: Optional[str] = None,
    ow: int = 100,
    aspect_ratio: str = "1:1",
) -> dict[str, Any]:
    """Compose a Midjourney v7 prompt from structured facets. Returns
    ``{ok, result: {prompt, facets_used}}``."""
    def go():
        prompt = _composer.compose(
            Subject(text=subject, constraints=constraints or []),
            style=StyleStack(
                moodboard=moodboard,
                sref=sref,
                stylize=stylize,
                style_raw=style_raw,
            ),
            identity=IdentityStack(oref=oref, ow=ow) if oref else None,
            aspect_ratio=aspect_ratio,
        )
        return {"prompt": prompt}
    return await _run_tool("compose_prompt", go)


@mcp.tool()
async def imagine(
    prompt: str,
    asset_id: str,
    upscale: Optional[str] = None,
) -> dict[str, Any]:
    """Fire one generation against the running bridge. Backend is sync —
    _run_tool dispatches it via asyncio.to_thread."""
    return await _run_tool(
        "imagine",
        _backend.imagine,
        prompt=prompt,
        asset_id=asset_id,
        upscale=upscale,
    )


@mcp.tool()
async def wait(job_id: str, timeout: int = 180) -> dict[str, Any]:
    """Block until the job hits ``done`` or ``failed`` or the timeout fires.
    Returns the full job record under ``result``."""
    return await _run_tool("wait", _backend.wait, job_id=job_id, timeout=timeout)


@mcp.tool()
async def status(job_id: str) -> dict[str, Any]:
    """Non-blocking status read."""
    return await _run_tool("status", _backend.status, job_id=job_id)


@mcp.tool()
async def bridge_health() -> dict[str, Any]:
    """Check whether the bridge daemon is up and the Discord WebSocket is
    connected."""
    return await _run_tool("bridge_health", _backend.health)


@mcp.tool()
async def crop_grid(
    src: str,
    quadrant: int,
    dest: Optional[str] = None,
) -> dict[str, Any]:
    """Crop one quadrant of an MJ grid. ``quadrant=0`` returns the whole
    image. If ``dest`` is set, write the cropped image to that path."""
    def go():
        img = crop_quadrant(src, quadrant)
        out: dict[str, Any] = {"w": img.size[0], "h": img.size[1]}
        if dest:
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            img.save(dest)
            out["dest"] = dest
        return out
    return await _run_tool("crop_grid", go)


@mcp.tool()
async def alpha_key(
    src: str,
    dest: str,
    tolerance: int = DEFAULT_TOLERANCE,
) -> dict[str, Any]:
    """Apply four-corner-average alpha keying. Reads ``src``, writes RGBA to
    ``dest``."""
    from PIL import Image
    def go():
        # Close the source loader explicitly. Review-flagged 2026-06-02 — long-
        # running MCP servers exhaust file descriptors otherwise.
        with Image.open(src) as img:
            keyed = alpha_key_corners(img, tolerance=tolerance)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        keyed.save(dest)
        return {"dest": dest, "w": keyed.size[0], "h": keyed.size[1]}
    return await _run_tool("alpha_key", go)


@mcp.tool()
async def promote(src: str, dest: str) -> dict[str, Any]:
    """Move a curated asset from staging into the consumer's asset tree."""
    def go():
        out = curation_promote(src, dest)
        return {"dest": str(out)}
    return await _run_tool("promote", go)


@mcp.tool()
async def log_append(
    asset_id: str,
    prompt: str,
    backend: str = "midjourney_discord",
    job_id: Optional[str] = None,
    upscale: Optional[str] = None,
    outputs: Optional[dict[str, Any]] = None,
    error: Optional[str] = None,
    agent_decision: Optional[str] = None,
    agent_reason: Optional[str] = None,
) -> dict[str, Any]:
    """Append a record to the prompt log.

    ``agent_decision`` must be one of: ``"promote"``, ``"reroll"``,
    ``"escalate"``, ``"dry_run"`` (or omitted). Invalid values produce a
    structured ValueError via the ``_run_tool`` envelope, naming the allowed
    set in the message.
    """
    def go():
        record = _log.append(
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
    return await _run_tool("log_append", go)


@mcp.tool()
async def read_prompt_log(n: Optional[int] = None) -> dict[str, Any]:
    """Read the prompt log back as structured records. ``n`` returns the
    last n entries; omit for all. This is the agent's working memory across
    loop iterations — the answer to 'what have I tried for this asset?'"""
    def go():
        return {"records": _log.read(n=n)}
    return await _run_tool("read_prompt_log", go)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


_mcp_shutdown_emitted = False


def _emit_mcp_shutdown(reason: str) -> None:
    global _mcp_shutdown_emitted
    if _mcp_shutdown_emitted:
        return
    _mcp_shutdown_emitted = True
    try:
        emit("MCP_SERVER_STOPPED", reason=reason)
    except Exception:
        pass


def main() -> None:
    import atexit
    import signal as _signal

    parser = argparse.ArgumentParser(prog="cascade-mcp")
    parser.add_argument(
        "--http",
        type=int,
        default=None,
        help="Run HTTP transport on the given port instead of stdio (default).",
    )
    args = parser.parse_args()

    transport = "http" if args.http else "stdio"
    emit("MCP_SERVER_STARTED", transport=transport)

    atexit.register(_emit_mcp_shutdown, "atexit")

    def _sig(signum, _frame):
        name = _signal.Signals(signum).name if isinstance(signum, int) else str(signum)
        _emit_mcp_shutdown(f"signal:{name}")
        raise SystemExit(0)

    try:
        _signal.signal(_signal.SIGINT, _sig)
        _signal.signal(_signal.SIGTERM, _sig)
    except (ValueError, OSError):
        pass

    try:
        if args.http:
            if hasattr(mcp, "run_sse_async"):
                import asyncio
                asyncio.run(mcp.run_sse_async(host="127.0.0.1", port=args.http))
            else:
                raise RuntimeError(
                    "HTTP transport not available in this mcp SDK version; "
                    "use stdio (omit --http) or upgrade mcp."
                )
        else:
            mcp.run()
    except Exception:
        _emit_mcp_shutdown("exception")
        raise


if __name__ == "__main__":
    main()

"""MCP server — the primary agent-facing surface for cascade-img.

Exposes the composer, backend, curation, and prompt-log as MCP tools that an
agent host (Claude Desktop, Cursor, Cline, Continue, custom frameworks) can
invoke directly. Every tool returns a structured dict; agents parse the shape
without scraping prose.

Start it with the ``cascade-mcp`` console script. Stdio transport by
default — the convention for Claude Desktop and Cursor. Pass ``--http <port>``
to run HTTP transport instead.

Every tool call emits ``MCP_TOOL_CALLED`` (before) and ``MCP_TOOL_COMPLETED``
or ``MCP_TOOL_FAILED`` (after). The locked vocabulary in
``vocabulary/versions/0.1.json`` is the contract.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import time
from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend
from cascade_img.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.curation import (
    DEFAULT_TOLERANCE,
    alpha_key_corners,
    crop_quadrant,
)
from cascade_img.curation import (
    promote as curation_promote,
)
from cascade_img.log import PromptLog
from cascade_img.vocabulary import emit

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
            # Sync callable: run on a worker thread so the asyncio loop stays
            # responsive while concurrent tool calls execute.
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
    constraints: list[str] | None = None,
    moodboard: str | None = None,
    sref: str | None = None,
    stylize: int | None = None,
    style_raw: bool = True,
    oref: str | None = None,
    ow: int = 100,
    aspect_ratio: str = "1:1",
    negatives: list[str] | None = None,
    image_prompts: list[str] | None = None,
    image_weight: float | None = None,
    tile: bool = False,
    chaos: int | None = None,
    weird: int | None = None,
    stop: int | None = None,
    quality: int | None = None,
    seed: int | None = None,
) -> dict[str, Any]:
    """Compose a Midjourney v7 prompt from composable prompt parts. Returns
    ``{ok, result: {prompt}}``.

    Beyond the style/identity parts: ``negatives`` becomes a single ``--no``
    clause; ``image_prompts`` are reference URLs prepended to the prompt with
    optional ``image_weight`` (``--iw``); ``tile``/``chaos``/``weird``/``stop``/
    ``quality``/``seed`` are render controls. Out-of-range values return a
    structured ValueError through the envelope."""
    def go():
        prompt = _composer.compose(
            Subject(
                text=subject,
                constraints=constraints or [],
                negatives=negatives or [],
                image_prompts=image_prompts or [],
                image_weight=image_weight,
            ),
            style=StyleStack(
                moodboard=moodboard,
                sref=sref,
                stylize=stylize,
                style_raw=style_raw,
            ),
            identity=IdentityStack(oref=oref, ow=ow) if oref else None,
            params=ParamStack(
                tile=tile,
                chaos=chaos,
                weird=weird,
                stop=stop,
                quality=quality,
                seed=seed,
            ),
            aspect_ratio=aspect_ratio,
        )
        return {"prompt": prompt}
    return await _run_tool("compose_prompt", go)


@mcp.tool()
async def imagine(
    prompt: str,
    asset_id: str,
    upscale: str | None = None,
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
    dest: str | None = None,
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
    method: str = "flood",
) -> dict[str, Any]:
    """Apply corner-anchored alpha keying. Reads ``src``, writes RGBA to ``dest``.

    ``method`` is ``"flood"`` (default — 4-connected flood-fill from each
    corner; correct for sprite-on-uniform-bg cases where the subject has a
    darker outline) or ``"threshold"`` (per-pixel distance from corner-average;
    faster but eats subject pixels whose color is close to the background).

    The returned ``keyed_ratio`` is the fraction of pixels keyed transparent
    (0.0-1.0). The agent can use it to detect failure: typical sprite outputs
    key 0.4-0.8 of the frame; ratios <0.1 mean the keyer didn't find the
    background (gradient/vignette/wrong tolerance); ratios >0.9 mean the keyer
    ate the subject and the result should be rejected or re-rolled.
    """
    from PIL import Image
    def go():
        # Close the source loader explicitly so long-running MCP servers
        # don't exhaust file descriptors.
        with Image.open(src) as img:
            keyed = alpha_key_corners(img, tolerance=tolerance, method=method)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        keyed.save(dest)
        # Count alpha=0 pixels via the alpha channel's histogram; bucket 0
        # is fully transparent. Cheaper than a Python pixel walk.
        keyed_count = keyed.getchannel("A").histogram()[0]
        total = keyed.size[0] * keyed.size[1]
        return {
            "dest": dest,
            "w": keyed.size[0],
            "h": keyed.size[1],
            "method": method,
            "tolerance": tolerance,
            "keyed_count": keyed_count,
            "total_count": total,
            "keyed_ratio": round(keyed_count / total, 4) if total else 0.0,
        }
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
async def read_prompt_log(n: int | None = None) -> dict[str, Any]:
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
    # Shutdown hook must never propagate.
    with contextlib.suppress(Exception):
        emit("MCP_SERVER_STOPPED", reason=reason)


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

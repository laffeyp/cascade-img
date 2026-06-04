"""MCP server wiring — the ``cascade-mcp`` entry point.

Builds the FastMCP instance, registers the tool surface from
:mod:`cascade_img.interfaces.mcp.tools` (one module per concern), and serves it.
Stdio transport by default — the convention for Claude Desktop and Cursor; pass
``--http <port>`` for SSE/HTTP instead.

Every tool call emits ``MCP_TOOL_CALLED`` (before) and ``MCP_TOOL_COMPLETED``
or ``MCP_TOOL_FAILED`` (after) via :func:`cascade_img.interfaces.mcp._envelope._run_tool`.

The tool functions are re-exported here so callers (and the test suite) can
``from cascade_img.interfaces.mcp.tool_server import compose_prompt`` and call
them directly, exactly as they're registered.
"""

from __future__ import annotations

import argparse
import contextlib

from mcp.server.fastmcp import FastMCP

from cascade_img.interfaces.mcp.tools import (
    ALL_TOOLS,
    alpha_key,
    auto_trim,
    bridge_health,
    compose_prompt,
    contact_sheet,
    crop_grid,
    imagine,
    log_append,
    mj_action,
    palette_quantize,
    promote,
    read_prompt_log,
    score_grid,
    sprite_sheet,
    status,
    wait,
)
from cascade_img.vocabulary import emit

__all__ = [
    "alpha_key",
    "auto_trim",
    "bridge_health",
    "compose_prompt",
    "contact_sheet",
    "crop_grid",
    "imagine",
    "log_append",
    "main",
    "mcp",
    "mj_action",
    "palette_quantize",
    "promote",
    "read_prompt_log",
    "score_grid",
    "sprite_sheet",
    "status",
    "wait",
]

mcp = FastMCP("cascade-mj")

# Register each tool: its __name__ is the MCP tool name, its docstring the
# description. Grouped by concern in ALL_TOOLS (prompt, generation, curation, log).
for _tool in ALL_TOOLS:
    mcp.add_tool(_tool)


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


def _serve_http(port: int) -> None:
    """Serve the MCP over SSE/HTTP on 127.0.0.1:``port``.

    FastMCP reads host/port from ``mcp.settings``; ``run_sse_async()`` takes no
    host/port arguments (passing them raises ``TypeError`` — which is exactly
    what the previous ``run_sse_async(host=..., port=...)`` call did, silently
    breaking ``cascade-mcp --http``). Set the settings, then run."""
    if not hasattr(mcp, "run_sse_async"):
        raise RuntimeError(
            "HTTP transport not available in this mcp SDK version; "
            "use stdio (omit --http) or upgrade mcp."
        )
    import asyncio

    mcp.settings.host = "127.0.0.1"
    mcp.settings.port = port
    asyncio.run(mcp.run_sse_async())


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
    except ValueError, OSError:
        pass

    try:
        if args.http:
            _serve_http(args.http)
        else:
            mcp.run()
    except Exception:
        _emit_mcp_shutdown("exception")
        raise


if __name__ == "__main__":
    main()

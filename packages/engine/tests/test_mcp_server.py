"""Behavior contract for the MCP server tools.

Calls the underlying tool functions directly (not through the MCP transport,
which is integration territory — those land in a later sprint). Verifies the
envelope (``{ok, result}`` or ``{ok: false, error: {code, ...}}``) and the
signal sequence (``MCP_TOOL_CALLED`` then ``MCP_TOOL_COMPLETED`` or
``MCP_TOOL_FAILED``).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cascade_img.mcp_server import (
    compose_prompt,
    crop_grid,
    log_append,
    promote,
    read_prompt_log,
)
from cascade_img.vocabulary import clear, snapshot


def _tags() -> list[str]:
    return [r["tag"] for r in snapshot()]


@pytest.mark.asyncio
async def test_compose_prompt_envelope_and_signals():
    clear()
    r = await compose_prompt(
        subject="a small finch",
        constraints=["side view"],
        moodboard="m1",
        sref="https://cdn/x.png",
        oref="https://cdn/oref.png",
        ow=400,
        aspect_ratio="1:1",
    )
    assert r["ok"] is True
    assert "prompt" in r["result"]
    assert "--p m1" in r["result"]["prompt"]
    assert "--oref" in r["result"]["prompt"]
    # signals
    tags = _tags()
    assert "MCP_TOOL_CALLED" in tags
    assert "MCP_TOOL_COMPLETED" in tags
    assert "PROMPT_COMPOSED" in tags  # the underlying composer fired
    # ordering: tool_called comes before tool_completed
    assert tags.index("MCP_TOOL_CALLED") < tags.index("MCP_TOOL_COMPLETED")


@pytest.mark.asyncio
async def test_crop_grid_writes_dest_and_returns_size(tmp_path: Path):
    clear()
    from PIL import Image
    src = tmp_path / "grid.png"
    Image.new("RGB", (200, 200), (100, 100, 100)).save(src)
    dest = tmp_path / "u2.png"
    r = await crop_grid(src=str(src), quadrant=2, dest=str(dest))
    assert r["ok"] is True
    assert r["result"]["w"] == 100
    assert r["result"]["h"] == 100
    assert dest.exists()
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_promote_envelope(tmp_path: Path):
    clear()
    src = tmp_path / "x.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 50)
    dest = tmp_path / "deep" / "y.png"
    r = await promote(src=str(src), dest=str(dest))
    assert r["ok"] is True
    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()
    tags = _tags()
    assert "MCP_TOOL_COMPLETED" in tags
    assert "ASSET_PROMOTED" in tags


@pytest.mark.asyncio
async def test_log_append_and_read_roundtrip(tmp_path: Path, monkeypatch):
    """log_append + read_prompt_log roundtrip uses the module-level log,
    which by default lives at CASCADE_PROMPT_LOG. Pointing it at a tmp file
    is via monkeypatching the module's _log attribute."""
    clear()
    from cascade_img import mcp_server
    from cascade_img.log import PromptLog
    monkeypatch.setattr(mcp_server, "_log", PromptLog(tmp_path / "log.jsonl"))

    r = await log_append(
        asset_id="bird",
        prompt="x",
        backend="midjourney_discord",
        job_id="abc",
        agent_decision="promote",
    )
    assert r["ok"] is True
    r2 = await read_prompt_log(n=5)
    assert r2["ok"] is True
    assert len(r2["result"]["records"]) == 1
    assert r2["result"]["records"][0]["agent_decision"] == "promote"


@pytest.mark.asyncio
async def test_run_tool_envelopes_exception_with_remediation():
    """An exception whose class carries `.code` and `.remediation` flows
    through `_run_tool` into the structured envelope unchanged."""
    from cascade_img.mcp_server import _run_tool
    clear()

    class TestError(Exception):
        code = "TEST_ERROR"
        remediation = "Read the docs."

    def failing():
        raise TestError("the thing broke")

    result = await _run_tool("fictional_tool", failing)
    assert result["ok"] is False
    assert result["error"]["code"] == "TEST_ERROR"
    assert result["error"]["message"] == "the thing broke"
    assert result["error"]["remediation"] == "Read the docs."
    tags = [r["tag"] for r in snapshot()]
    assert "MCP_TOOL_FAILED" in tags


@pytest.mark.asyncio
async def test_run_tool_envelopes_bare_exception_without_remediation():
    """An exception without `.code` or `.remediation` still routes through;
    code is the class name, remediation absent."""
    from cascade_img.mcp_server import _run_tool
    clear()

    def failing():
        raise ValueError("bad input")

    result = await _run_tool("fictional_tool", failing)
    assert result["ok"] is False
    assert result["error"]["code"] == "ValueError"
    assert result["error"]["message"] == "bad input"
    assert "remediation" not in result["error"]


@pytest.mark.asyncio
async def test_failure_path_returns_structured_error(tmp_path: Path):
    """A tool that raises returns {ok: false, error: {code, message}} and
    emits MCP_TOOL_FAILED."""
    clear()
    r = await promote(
        src=str(tmp_path / "does-not-exist.png"),
        dest=str(tmp_path / "y.png"),
    )
    assert r["ok"] is False
    assert "code" in r["error"]
    assert r["error"]["code"] == "FileNotFoundError"
    assert "MCP_TOOL_FAILED" in _tags()

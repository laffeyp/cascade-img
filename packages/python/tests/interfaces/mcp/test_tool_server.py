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

from cascade_img.interfaces.mcp.tool_server import (
    alpha_key,
    bridge_health,
    compose_prompt,
    crop_grid,
    imagine,
    log_append,
    mj_action,
    promote,
    read_prompt_log,
    score_grid,
    status,
    wait,
)
from cascade_img.vocabulary import clear, snapshot


class _FakeBackend:
    """Sync stub matching the real backend's contract (methods are sync at
    v0.1; _run_tool dispatches them via asyncio.to_thread). Lets the
    bridge-facing tools be exercised with no live daemon."""

    def imagine(self, prompt: str, asset_id: str, upscale=None) -> dict:
        return {"job_id": "job-1", "asset_id": asset_id, "status": "submitted", "upscale": upscale}

    def wait(self, job_id: str, timeout: int = 180) -> dict:
        return {
            "job_id": job_id,
            "status": "done",
            "grid_path": "/tmp/g.webp",
            "image_path": "/tmp/g.webp",
        }

    def status(self, job_id: str) -> dict:
        return {"job_id": job_id, "status": "progress"}

    def health(self) -> dict:
        return {"discord_ready": True, "pending_grid": 0, "total_jobs": 0}

    def action(self, job_id: str, action: str, slot: int | None = None) -> dict:
        return {
            "job_id": job_id,
            "action": action,
            "slot": slot,
            "custom_id": f"MJ::JOB::{action}::1::uuid::SOLO",
            "message_id": 42,
        }


def _tags() -> list[str]:
    return [r["tag"] for r in snapshot()]


@pytest.mark.asyncio
async def test_compose_prompt_envelope_and_signals():
    clear()
    r = await compose_prompt(
        subject="a mountain",
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
    from cascade_img.interfaces.mcp import _envelope
    from cascade_img.prompt.prompt_log import PromptLog

    monkeypatch.setattr(_envelope, "_log", PromptLog(tmp_path / "log.jsonl"))

    r = await log_append(
        asset_id="mountain-icon",
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
    from cascade_img.interfaces.mcp._envelope import _run_tool

    clear()

    class TestError(Exception):
        code = "TEST_ERROR"
        remediation = "Read the docs."

    def failing():
        raise TestError("the thing broke")

    result = await _run_tool("promote", failing)
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
    from cascade_img.interfaces.mcp._envelope import _run_tool

    clear()

    def failing():
        raise ValueError("bad input")

    result = await _run_tool("promote", failing)
    assert result["ok"] is False
    assert result["error"]["code"] == "ValueError"
    assert result["error"]["message"] == "bad input"
    assert "remediation" not in result["error"]


@pytest.mark.asyncio
async def test_imagine_tool_envelope_and_signals(monkeypatch):
    """imagine() is the tool an agent fires generations with — exercise it
    against a stubbed sync backend (it was previously never called)."""
    from cascade_img.interfaces.mcp import _envelope

    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await imagine(prompt="a mountain --v 7", asset_id="mountain-icon", upscale=None)
    assert r["ok"] is True
    assert r["result"]["job_id"] == "job-1"
    tags = _tags()
    assert "MCP_TOOL_CALLED" in tags
    assert "MCP_TOOL_COMPLETED" in tags


@pytest.mark.asyncio
async def test_wait_status_health_tools(monkeypatch):
    from cascade_img.interfaces.mcp import _envelope

    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    rw = await wait(job_id="job-1", timeout=5)
    assert rw["ok"] is True and rw["result"]["status"] == "done"
    rs = await status(job_id="job-1")
    assert rs["ok"] is True and rs["result"]["status"] == "progress"
    rh = await bridge_health()
    assert rh["ok"] is True and rh["result"]["discord_ready"] is True


@pytest.mark.asyncio
async def test_mj_action_tool_envelope_and_signals(monkeypatch):
    """mj_action drives a response-message button through the backend. Exercise
    the envelope + signal pair against the stub (no live daemon)."""
    from cascade_img.interfaces.mcp import _envelope

    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await mj_action(job_id="job-1", action="vary_strong")
    assert r["ok"] is True
    assert r["result"]["action"] == "vary_strong"
    assert r["result"]["message_id"] == 42
    tags = _tags()
    assert "MCP_TOOL_CALLED" in tags
    assert "MCP_TOOL_COMPLETED" in tags


@pytest.mark.asyncio
async def test_alpha_key_tool_keys_and_reports_ratio(tmp_path: Path):
    """alpha_key returns a keyed_ratio the agent branches on; feed
    a synthetic image and assert the envelope + ratio band + signal."""
    clear()
    from PIL import Image

    src = tmp_path / "k.png"
    Image.new("RGBA", (64, 64), (255, 255, 255, 255)).save(src)
    dest = tmp_path / "k_out.png"
    r = await alpha_key(src=str(src), dest=str(dest), tolerance=40, method="flood")
    assert r["ok"] is True
    assert dest.exists()
    assert r["result"]["method"] == "flood"
    assert 0.0 <= r["result"]["keyed_ratio"] <= 1.0
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_score_grid_tool(tmp_path: Path):
    clear()
    from PIL import Image, ImageDraw

    g = Image.new("RGB", (64, 64), (128, 128, 128))
    ImageDraw.Draw(g).rectangle((0, 0, 31, 31), fill=(0, 0, 0))  # one dark quadrant
    src = tmp_path / "grid.png"
    g.save(src)
    r = await score_grid(src=str(src))
    assert r["ok"] is True
    assert len(r["result"]["scores"]) == 4
    assert "MCP_TOOL_COMPLETED" in _tags()


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


def test_serve_http_sets_host_port_on_settings(monkeypatch):
    """FastMCP.run_sse_async takes NO host/port args — they go on mcp.settings.
    Regression guard for the --http transport (the old run_sse_async(host=,
    port=) call would TypeError at runtime). The fake mirrors the real
    no-argument signature, so a revert to kwargs fails this test."""
    from cascade_img.interfaces.mcp import tool_server

    called = {"ran": False}

    async def _fake_run_sse_async():
        called["ran"] = True

    monkeypatch.setattr(tool_server.mcp, "run_sse_async", _fake_run_sse_async)
    tool_server._serve_http(8123)
    assert called["ran"] is True
    assert tool_server.mcp.settings.host == "127.0.0.1"
    assert tool_server.mcp.settings.port == 8123

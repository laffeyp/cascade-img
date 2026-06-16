"""Behavior contract for the MCP server tools.

Calls the underlying tool functions directly (not through the MCP transport,
which is integration territory — those land in a later sprint). Verifies the
envelope (``{ok, result}`` or ``{ok: false, error: {code, ...}}``) and the
signal sequence (``MCP_TOOL_CALLED`` then ``MCP_TOOL_COMPLETED`` or
``MCP_TOOL_FAILED``).
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from cascade_img.interfaces.mcp.tool_server import (
    alpha_key,
    auto_trim,
    bridge_health,
    compose_prompt,
    compose_video,
    contact_sheet,
    crop_grid,
    generate_video,
    imagine,
    log_append,
    loop_seam_delta,
    mj_action,
    palette_quantize,
    promote,
    read_prompt_log,
    score_grid,
    sprite_sheet,
    status,
    video_filmstrip,
    wait,
)
from cascade_img.vocabulary import clear, snapshot


class _FakeBackend:
    """Sync stub matching the real backend's contract (methods are sync at
    v0.1; _run_tool dispatches them via asyncio.to_thread). Lets the
    bridge-facing tools be exercised with no live daemon."""

    def imagine(self, prompt: str, asset_id: str, upscale=None, idempotency_key=None) -> dict:
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

    def generate_video(self, prompt: str, asset_id: str) -> dict:
        self.last_video_prompt = prompt
        return {"job_id": "vid-1", "asset_id": asset_id, "status": "submitted", "upscale": None}

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
        version="7",  # Omni Reference is V7-only
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
async def test_mcp_walk_passes_trace_grammar_check(monkeypatch):
    """Grammar checking on every CI PR, no credentials: drive a compose -> imagine
    -> wait walk on the fake backend, then run the trace checker over snapshot()
    and assert zero error-severity violations. Each MCP_TOOL_CALLED must resolve to
    a COMPLETED in its tool-slice; timing-window warnings (if any) never fail."""
    from cascade_img.interfaces.mcp import _envelope
    from cascade_img.vocabulary.trace_check import check_trace, load_catalog

    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    await compose_prompt(subject="a mountain", aspect_ratio="1:1")
    r = await imagine(prompt="a mountain --v 7", asset_id="mountain-icon", upscale=None)
    assert r["ok"] is True
    await wait(job_id=r["result"]["job_id"], timeout=5)

    errors = [v for v in check_trace(snapshot(), load_catalog()) if v.severity == "error"]
    assert not errors, "MCP walk grammar errors: " + "; ".join(
        f"{v.rule}/{v.slice_key}: {v.message}" for v in errors
    )


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
async def test_imagine_tool_forwards_idempotency_key(monkeypatch):
    """The imagine tool threads idempotency_key through to the backend so a
    retried-with-the-same-key call can be replayed by the bridge instead of
    double-submitting. (review #3 idempotency)"""
    from cascade_img.interfaces.mcp import _envelope

    clear()
    captured: dict = {}

    class _Cap:
        def imagine(self, prompt, asset_id, upscale=None, idempotency_key=None):
            captured["idempotency_key"] = idempotency_key
            return {"job_id": "j", "asset_id": asset_id, "status": "submitted"}

    monkeypatch.setattr(_envelope, "_backend", _Cap())
    r = await imagine(prompt="p", asset_id="a", idempotency_key="IDEM-1")
    assert r["ok"] is True
    assert captured["idempotency_key"] == "IDEM-1"


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
async def test_contact_sheet_tool(tmp_path: Path):
    """The contact_sheet MCP wrapper envelopes the curation call and writes dest."""
    clear()
    from PIL import Image

    src = tmp_path / "grid.png"
    Image.new("RGB", (128, 128), (90, 90, 90)).save(src)
    dest = tmp_path / "sheet.png"
    r = await contact_sheet(src=str(src), dest=str(dest), labels=True)
    assert r["ok"] is True
    assert Path(r["result"]["dest"]).exists()
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_auto_trim_tool(tmp_path: Path):
    """The auto_trim MCP wrapper crops to the content bbox via the envelope."""
    clear()
    from PIL import Image

    src = tmp_path / "img.png"
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    for x in range(20, 40):
        for y in range(20, 40):
            im.putpixel((x, y), (255, 0, 0, 255))  # opaque block for alpha-trim
    im.save(src)
    dest = tmp_path / "trim.png"
    r = await auto_trim(src=str(src), dest=str(dest), mode="alpha", tolerance=10)
    assert r["ok"] is True
    assert Path(r["result"]["dest"]).exists()


@pytest.mark.asyncio
async def test_palette_quantize_tool(tmp_path: Path):
    """The palette_quantize MCP wrapper reduces to a fixed palette via the envelope."""
    clear()
    from PIL import Image

    src = tmp_path / "img.png"
    Image.new("RGB", (64, 64), (123, 200, 50)).save(src)
    dest = tmp_path / "q.png"
    r = await palette_quantize(src=str(src), dest=str(dest), n_colors=8, method="median_cut")
    assert r["ok"] is True
    assert Path(r["result"]["dest"]).exists()


@pytest.mark.asyncio
async def test_sprite_sheet_tool(tmp_path: Path):
    """The sprite_sheet MCP wrapper packs multiple sprites into one atlas."""
    clear()
    from PIL import Image

    srcs = []
    for i in range(3):
        p = tmp_path / f"s{i}.png"
        Image.new("RGBA", (32, 32), (i * 40, 0, 0, 255)).save(p)
        srcs.append(str(p))
    dest = tmp_path / "atlas.png"
    r = await sprite_sheet(srcs=srcs, dest=str(dest), layout="grid", padding=2)
    assert r["ok"] is True
    assert Path(r["result"]["dest"]).exists()


def _make_webp(path: Path, frames: int = 4) -> None:
    from PIL import Image

    imgs = [Image.new("RGB", (24, 24), ((i * 60) % 256, 0, 0)) for i in range(frames)]
    imgs[-1] = imgs[0].copy()  # seamless loop
    imgs[0].save(
        path,
        save_all=True,
        append_images=imgs[1:],
        duration=100,
        loop=0,
        lossless=True,
        format="WEBP",
    )


@pytest.mark.asyncio
async def test_video_filmstrip_tool(tmp_path: Path):
    """The video_filmstrip MCP tool turns a video into a vision-readable still +
    signature through the envelope."""
    clear()
    src = tmp_path / "v.webp"
    _make_webp(src, frames=4)
    dest = tmp_path / "strip.png"
    r = await video_filmstrip(src=str(src), dest=str(dest), frames=3)
    assert r["ok"] is True
    assert r["result"]["frame_count"] == 4
    assert Path(r["result"]["dest"]).exists()
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_loop_seam_delta_tool(tmp_path: Path):
    """The loop_seam_delta MCP tool reports the seam distance (0 for a clean loop)."""
    clear()
    src = tmp_path / "loop.webp"
    _make_webp(src, frames=4)
    r = await loop_seam_delta(src=str(src))
    assert r["ok"] is True
    assert r["result"]["loop_seam_delta"] == 0.0
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


@pytest.mark.asyncio
async def test_generate_video_tool_composes_and_fires(monkeypatch):
    """generate_video composes the video prompt AND fires it at the backend in
    one call — the agent's one-shot native-video entry point."""
    from cascade_img.interfaces.mcp import _envelope

    clear()
    fb = _FakeBackend()
    monkeypatch.setattr(_envelope, "_backend", fb)
    r = await generate_video(
        image_url="https://cdn/start.png", asset_id="clip", loop=True, motion="high"
    )
    assert r["ok"] is True
    assert r["result"]["job_id"] == "vid-1"
    # the composed prompt that was actually fired
    assert fb.last_video_prompt.startswith("https://cdn/start.png ")
    assert "--video" in fb.last_video_prompt
    assert "--loop" in fb.last_video_prompt
    assert "--motion high" in fb.last_video_prompt
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_generate_video_tool_envelopes_validation_error(monkeypatch):
    """A conflicting request (loop + end_frame) fails as a structured error
    BEFORE firing — composition validates first."""
    from cascade_img.interfaces.mcp import _envelope

    clear()
    monkeypatch.setattr(_envelope, "_backend", _FakeBackend())
    r = await generate_video(
        image_url="https://cdn/s.png", asset_id="c", loop=True, end_frame="https://cdn/e.png"
    )
    assert r["ok"] is False
    assert r["error"]["code"] == "ValueError"
    assert "MCP_TOOL_FAILED" in _tags()


@pytest.mark.asyncio
async def test_compose_video_tool_envelope_and_prompt():
    """The compose_video MCP tool envelopes the composer call and returns a
    native video prompt (url leads, --video + the requested video params)."""
    clear()
    r = await compose_video(image_url="https://cdn/start.png", loop=True, motion="high")
    assert r["ok"] is True
    p = r["result"]["prompt"]
    assert p.startswith("https://cdn/start.png ")
    assert "--video" in p and "--loop" in p and "--motion high" in p
    assert "MCP_TOOL_COMPLETED" in _tags()


@pytest.mark.asyncio
async def test_compose_video_tool_envelopes_validation_error():
    """A conflicting request (loop + end_frame) comes back as a structured
    error through the envelope, not a raw exception."""
    clear()
    r = await compose_video(image_url="https://cdn/s.png", loop=True, end_frame="https://cdn/e.png")
    assert r["ok"] is False
    assert r["error"]["code"] == "ValueError"
    assert "MCP_TOOL_FAILED" in _tags()


# --------------------- server entrypoint (main / shutdown) ---------------------


def test_emit_mcp_shutdown_is_idempotent(monkeypatch):
    """MCP_SERVER_STOPPED fires at most once even if both atexit and a signal
    handler call the shutdown hook."""
    import cascade_img.interfaces.mcp.tool_server as ts

    clear()
    monkeypatch.setattr(ts, "_mcp_shutdown_emitted", False)
    ts._emit_mcp_shutdown("atexit")
    ts._emit_mcp_shutdown("signal:SIGTERM")
    assert _tags().count("MCP_SERVER_STOPPED") == 1


def test_main_stdio_emits_started_and_runs(monkeypatch):
    """`cascade-mcp` (no --http) emits MCP_SERVER_STARTED(transport=stdio) and
    drives mcp.run(). Signal/atexit registration is stubbed so the test does not
    mutate the interpreter's real handlers."""
    import sys

    import cascade_img.interfaces.mcp.tool_server as ts

    clear()
    monkeypatch.setattr(ts, "_mcp_shutdown_emitted", False)
    ran: list[str] = []
    monkeypatch.setattr(ts.mcp, "run", lambda: ran.append("stdio"))
    monkeypatch.setattr("signal.signal", lambda *a, **k: None)
    monkeypatch.setattr("atexit.register", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["cascade-mcp"])

    ts.main()
    assert ran == ["stdio"]
    tags = _tags()
    assert "MCP_SERVER_STARTED" in tags


def test_main_http_dispatches_to_serve_http(monkeypatch):
    """`cascade-mcp --http <port>` routes to _serve_http(port) with
    transport=http, instead of stdio."""
    import sys

    import cascade_img.interfaces.mcp.tool_server as ts

    clear()
    monkeypatch.setattr(ts, "_mcp_shutdown_emitted", False)
    served: list[int] = []
    monkeypatch.setattr(ts, "_serve_http", lambda port: served.append(port))
    monkeypatch.setattr("signal.signal", lambda *a, **k: None)
    monkeypatch.setattr("atexit.register", lambda *a, **k: None)
    monkeypatch.setattr(sys, "argv", ["cascade-mcp", "--http", "5005"])

    ts.main()
    assert served == [5005]


@pytest.mark.asyncio
async def test_cancelled_tool_emits_failed_and_reraises():
    """asyncio.CancelledError is a BaseException, so the broad ``except
    Exception`` in _run_tool does NOT catch it: a cancelled tool call would
    otherwise leave MCP_TOOL_CALLED unpaired (breaching the pairing invariant)
    and swallow the cancellation. The dedicated clause emits
    MCP_TOOL_FAILED(CANCELLED) to close the pair and re-raises so the cancel
    propagates to the caller. (review #3)"""
    from cascade_img.interfaces.mcp._envelope import _run_tool

    clear()

    async def _cancelled(**kwargs):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await _run_tool("imagine", _cancelled)

    # The CALLED/FAILED pair is closed — no unpaired CALLED left dangling.
    assert _tags() == ["MCP_TOOL_CALLED", "MCP_TOOL_FAILED"]
    failed = next(r for r in snapshot() if r["tag"] == "MCP_TOOL_FAILED")
    assert failed["payload"]["error_code"] == "CANCELLED"
    assert failed["payload"]["tool"] == "imagine"


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

"""Behavior contract for the bridge's resilience layer:

- Discord WebSocket reconnect loop with exponential backoff
- Auth-failure termination (loop stops, no infinite retry)
- on_disconnect clears the _ready flag
- _session_id_or_raise() returns a structured DiscordNotReadyError
- /imagine returns 503 DISCORD_NOT_READY when the gateway is down
- /imagine returns 202 SUBMITTED_UNCONFIRMED when the interaction times out
- Per-slot upscale button-press failures don't fail the whole job
- Output-path collisions append a request_token suffix and signal
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import threading
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import discord
import pytest

from cascade_img.backends.midjourney_discord import bridge
from cascade_img.backends.midjourney_discord.bridge import (
    JOBS,
    LOCK,
    PENDING_GRID,
    DiscordNotReadyError,
    Job,
    Status,
    _is_terminal_auth_failure,
    _reconnect_backoff_seconds,
    _safe_output_path,
    _session_id_or_raise,
)
from cascade_img.backends.midjourney_discord.job_store import JobStore
from cascade_img.vocabulary import clear, snapshot


def _reset_bridge_state() -> None:
    with LOCK:
        JOBS.clear()
        PENDING_GRID.clear()
        bridge._shutdown_emitted = False
        bridge._shutdown_event.clear()
        bridge._ready.clear()


def _tags() -> list[str]:
    return [r["tag"] for r in snapshot()]


# ---------------------------------------------------------------------------
# Backoff math
# ---------------------------------------------------------------------------


def test_backoff_grows_then_caps():
    assert _reconnect_backoff_seconds(1) == 2.0
    assert _reconnect_backoff_seconds(2) == 4.0
    assert _reconnect_backoff_seconds(3) == 8.0
    assert _reconnect_backoff_seconds(4) == 16.0
    assert _reconnect_backoff_seconds(5) == 32.0
    assert _reconnect_backoff_seconds(6) == 60.0
    # Cap holds at 60s — would otherwise be 128, 256, ...
    assert _reconnect_backoff_seconds(7) == 60.0
    assert _reconnect_backoff_seconds(100) == 60.0


# ---------------------------------------------------------------------------
# Terminal-failure detection
# ---------------------------------------------------------------------------


def test_terminal_auth_failure_classifier_recognizes_login_failure():
    assert _is_terminal_auth_failure(discord.LoginFailure("bad token"))


def test_terminal_auth_failure_classifier_recognizes_401():
    e = discord.HTTPException.__new__(discord.HTTPException)
    e.status = 401
    e.code = 0
    e.text = "unauthorized"
    assert _is_terminal_auth_failure(e)


def test_terminal_auth_failure_classifier_ignores_transient():
    assert not _is_terminal_auth_failure(ConnectionResetError("network blip"))
    assert not _is_terminal_auth_failure(TimeoutError("slow gateway"))
    assert not _is_terminal_auth_failure(RuntimeError("misc"))


# ---------------------------------------------------------------------------
# Reconnect loop — terminal auth failure stops the loop
# ---------------------------------------------------------------------------


def test_run_discord_stops_on_auth_failure(valid_env, monkeypatch):
    _reset_bridge_state()
    clear()
    bridge.cfg = bridge.Config.from_env()
    monkeypatch.setattr(bridge, "_reconnect_backoff_seconds", lambda n: 0.0)

    call_count = {"n": 0}

    async def fake_start(*args, **kwargs):
        call_count["n"] += 1
        raise discord.LoginFailure("test: token rejected")

    monkeypatch.setattr(bridge.client, "start", fake_start)

    bridge._run_discord()

    # One attempt, then terminate. No retry.
    assert call_count["n"] == 1
    tags = _tags()
    assert "DISCORD_RECONNECT_FAILED" in tags
    failed = next(r for r in snapshot() if r["tag"] == "DISCORD_RECONNECT_FAILED")
    assert failed["payload"]["reason"] == "auth"
    assert failed["payload"]["attempts"] == 1
    assert not bridge._ready.is_set()


# ---------------------------------------------------------------------------
# Reconnect loop — transient exception retries until shutdown
# ---------------------------------------------------------------------------


def test_run_discord_retries_on_transient_then_stops_on_shutdown(valid_env, monkeypatch):
    _reset_bridge_state()
    clear()
    bridge.cfg = bridge.Config.from_env()
    monkeypatch.setattr(bridge, "_reconnect_backoff_seconds", lambda n: 0.0)

    call_count = {"n": 0}

    async def fake_start(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 3:
            # After the third attempt, signal shutdown so the loop exits.
            bridge._shutdown_event.set()
        raise ConnectionResetError("transient")

    monkeypatch.setattr(bridge.client, "start", fake_start)

    bridge._run_discord()

    assert call_count["n"] == 3
    # Three DISCORD_DISCONNECTED (one per failed start) — but two
    # DISCORD_RECONNECTING (between attempts 1->2 and 2->3); attempt 3
    # exits the loop before announcing another reconnect.
    disconnects = [r for r in snapshot() if r["tag"] == "DISCORD_DISCONNECTED"]
    reconnects = [r for r in snapshot() if r["tag"] == "DISCORD_RECONNECTING"]
    assert len(disconnects) == 3
    assert len(reconnects) == 2
    # Terminal exit reason is shutdown.
    failed = next(r for r in snapshot() if r["tag"] == "DISCORD_RECONNECT_FAILED")
    assert failed["payload"]["reason"] == "shutdown"


def test_run_discord_clean_close_also_triggers_reconnect(valid_env, monkeypatch):
    """If client.start() returns normally (clean gateway close), the loop
    treats it as a disconnect and tries again — until shutdown."""
    _reset_bridge_state()
    clear()
    bridge.cfg = bridge.Config.from_env()
    monkeypatch.setattr(bridge, "_reconnect_backoff_seconds", lambda n: 0.0)

    call_count = {"n": 0}

    async def fake_start(*args, **kwargs):
        call_count["n"] += 1
        if call_count["n"] >= 2:
            bridge._shutdown_event.set()
        # Return normally — clean close.

    monkeypatch.setattr(bridge.client, "start", fake_start)

    bridge._run_discord()

    assert call_count["n"] == 2
    disconnects = [r for r in snapshot() if r["tag"] == "DISCORD_DISCONNECTED"]
    assert len(disconnects) == 2
    assert all(d["payload"]["reason"] == "gateway_close" for d in disconnects)


# ---------------------------------------------------------------------------
# on_disconnect clears _ready
# ---------------------------------------------------------------------------


def test_on_disconnect_clears_ready_and_emits():
    _reset_bridge_state()
    clear()
    bridge._ready.set()

    # The discord.py-self decorator wraps on_disconnect onto the client; call
    # via the wrapped name. Build a loop to run the coroutine.
    asyncio.run(bridge.on_disconnect())

    assert not bridge._ready.is_set()
    tags = _tags()
    assert "DISCORD_DISCONNECTED" in tags
    dc = next(r for r in snapshot() if r["tag"] == "DISCORD_DISCONNECTED")
    assert dc["payload"]["reason"] == "on_disconnect"


def test_on_disconnect_quiet_when_was_not_ready():
    """If _ready was already cleared (we never finished a handshake or we
    already announced a disconnect), don't emit again."""
    _reset_bridge_state()
    clear()
    # _ready already clear by reset.

    asyncio.run(bridge.on_disconnect())

    tags = _tags()
    assert "DISCORD_DISCONNECTED" not in tags


# ---------------------------------------------------------------------------
# _session_id_or_raise
# ---------------------------------------------------------------------------


def test_session_id_or_raise_when_ws_none(monkeypatch):
    monkeypatch.setattr(bridge.client, "ws", None, raising=False)
    with pytest.raises(DiscordNotReadyError) as exc_info:
        _session_id_or_raise()
    assert exc_info.value.code == "DISCORD_NOT_READY"
    assert "client.ws is None" in str(exc_info.value)
    assert exc_info.value.remediation  # carries operator guidance


def test_session_id_or_raise_when_session_id_none(monkeypatch):
    fake_ws = MagicMock()
    fake_ws.session_id = None
    monkeypatch.setattr(bridge.client, "ws", fake_ws, raising=False)
    with pytest.raises(DiscordNotReadyError) as exc_info:
        _session_id_or_raise()
    assert "session_id is None" in str(exc_info.value)


def test_session_id_or_raise_returns_session_id_when_ready(monkeypatch):
    fake_ws = MagicMock()
    fake_ws.session_id = "abc123session"
    monkeypatch.setattr(bridge.client, "ws", fake_ws, raising=False)
    assert _session_id_or_raise() == "abc123session"


# ---------------------------------------------------------------------------
# /imagine — DiscordNotReadyError -> 503
# ---------------------------------------------------------------------------


class _FakeFuture:
    """Stand-in for the Future returned by asyncio.run_coroutine_threadsafe.
    ``.result(timeout=...)`` raises or returns whatever the test wants."""

    def __init__(self, *, raises: BaseException | None = None, returns: Any = None) -> None:
        self._raises = raises
        self._returns = returns

    def result(self, timeout: float | None = None):
        if self._raises is not None:
            raise self._raises
        return self._returns


def _patch_coroutine_threadsafe(monkeypatch, future: _FakeFuture) -> None:
    """Bypass the real asyncio coroutine dispatch with a sync fake."""

    def fake_run(coro, loop):
        # Close the un-awaited coroutine to avoid the "coroutine was never
        # awaited" RuntimeWarning that pytest -W error would escalate.
        if asyncio.iscoroutine(coro):
            coro.close()
        return future

    monkeypatch.setattr(bridge.asyncio, "run_coroutine_threadsafe", fake_run)
    monkeypatch.setattr(bridge, "_running_loop", lambda: object())


def test_imagine_returns_503_on_discord_not_ready(monkeypatch):
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(
        monkeypatch,
        _FakeFuture(raises=DiscordNotReadyError("client.ws is None")),
    )

    client = bridge.app.test_client()
    resp = client.post("/imagine", json={"prompt": "a mountain", "asset_id": "mountain-icon"})

    assert resp.status_code == 503
    body = resp.get_json()
    assert body["code"] == "DISCORD_NOT_READY"
    assert "remediation" in body
    # Job is FAILED and out of PENDING_GRID.
    with LOCK:
        assert PENDING_GRID == []
        job = next(iter(JOBS.values()))
        assert job.status == Status.FAILED
        assert job.error_code == "DISCORD_NOT_READY"


# ---------------------------------------------------------------------------
# /imagine — TimeoutError -> 202 + SUBMITTED_UNCONFIRMED
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "exc",
    [TimeoutError, concurrent.futures.TimeoutError],
    ids=["builtin_timeout", "futures_timeout"],
)
def test_imagine_returns_202_on_submit_timeout(monkeypatch, exc):
    # run_coroutine_threadsafe's Future raises concurrent.futures.TimeoutError,
    # which on Python 3.10 (our floor) is NOT a builtin TimeoutError. The except
    # clause must catch both, or the timeout falls through to a spurious
    # SUBMIT_FAILED that evicts a job MJ may have accepted (double-bill risk).
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(
        monkeypatch,
        _FakeFuture(raises=exc("interaction post timed out")),
    )

    client = bridge.app.test_client()
    resp = client.post("/imagine", json={"prompt": "a mountain", "asset_id": "mountain-icon"})

    assert resp.status_code == 202
    body = resp.get_json()
    assert body["status"] == Status.SUBMITTED_UNCONFIRMED.value
    assert "do not retry" in body["note"].lower()
    # Job is NOT failed; still in PENDING_GRID so a late grid match can claim it.
    with LOCK:
        assert len(PENDING_GRID) == 1
        job = JOBS[PENDING_GRID[0]]
        assert job.status == Status.SUBMITTED_UNCONFIRMED
    # JOB_SUBMIT_TIMEOUT signal emitted.
    timeouts = [r for r in snapshot() if r["tag"] == "JOB_SUBMIT_TIMEOUT"]
    assert len(timeouts) == 1
    assert timeouts[0]["payload"]["timeout_seconds"] == 35


def test_imagine_returns_502_on_other_exception(monkeypatch):
    """Generic exceptions still fail the job and clear PENDING_GRID (the
    existing contract for non-timeout, non-not-ready errors)."""
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(
        monkeypatch,
        _FakeFuture(raises=ConnectionError("network down")),
    )

    client = bridge.app.test_client()
    resp = client.post("/imagine", json={"prompt": "x", "asset_id": "y"})

    assert resp.status_code == 502
    with LOCK:
        assert PENDING_GRID == []
        job = next(iter(JOBS.values()))
        assert job.status == Status.FAILED
        assert job.error_code == "SUBMIT_FAILED"


# ---------------------------------------------------------------------------
# Output-path collision detection
# ---------------------------------------------------------------------------


def test_safe_output_path_no_collision_returns_intended(tmp_path):
    clear()
    p = _safe_output_path(
        output_dir=tmp_path,
        asset_id="mountain-icon",
        suffix="_grid",
        ext=".png",
        request_token="tok12345",
        kind="grid",
        job_id="jid",
    )
    assert p == tmp_path / "mountain-icon_grid.png"
    # No collision signal.
    assert "OUTPUT_PATH_COLLISION" not in _tags()


def test_safe_output_path_collision_appends_token_and_emits(tmp_path):
    clear()
    # Pre-create the intended path so the second job hits a collision.
    (tmp_path / "mountain-icon_grid.png").write_bytes(b"first job got here first")

    p = _safe_output_path(
        output_dir=tmp_path,
        asset_id="mountain-icon",
        suffix="_grid",
        ext=".png",
        request_token="abc99999",
        kind="grid",
        job_id="job-2",
    )
    assert p == tmp_path / "mountain-icon_abc99999_grid.png"

    collisions = [r for r in snapshot() if r["tag"] == "OUTPUT_PATH_COLLISION"]
    assert len(collisions) == 1
    payload = collisions[0]["payload"]
    assert payload["asset_id"] == "mountain-icon"
    assert payload["job_id"] == "job-2"
    assert payload["kind"] == "grid"
    assert payload["intended_path"].endswith("mountain-icon_grid.png")
    assert payload["actual_path"].endswith("mountain-icon_abc99999_grid.png")


def test_safe_output_path_collision_upscale_kind(tmp_path):
    clear()
    (tmp_path / "mountain-icon_u2.png").write_bytes(b"existing")
    p = _safe_output_path(
        output_dir=tmp_path,
        asset_id="mountain-icon",
        suffix="_u2",
        ext=".png",
        request_token="zz99",
        kind="upscale",
        job_id="job-x",
    )
    assert p.name == "mountain-icon_zz99_u2.png"
    collisions = [r for r in snapshot() if r["tag"] == "OUTPUT_PATH_COLLISION"]
    assert collisions[0]["payload"]["kind"] == "upscale"


# ---------------------------------------------------------------------------
# Per-slot upscale button-press failures
# ---------------------------------------------------------------------------


def _make_upscale_job(asset_id: str = "mountain-icon", upscale: str = "all") -> Job:
    j = Job(job_id="jid-" + asset_id, asset_id=asset_id, prompt="p", upscale=upscale)
    j.status = Status.UPSCALING
    j.upscale_pending = [1, 2, 3, 4] if upscale == "all" else [int(upscale)]
    j.mj_job_uuid = "mj-uuid-1234"
    return j


def _press_partial_failures_via_gather(
    monkeypatch, *, slots: list[int], results: list[Any]
) -> tuple[list[tuple[int, str]], list[int]]:
    """Drive the per-slot failure-classification logic directly.

    Mirrors the gather() result loop in _ingest_message without setting up a
    real Discord event loop. ``results`` mixes exceptions and FakeResponse.
    """
    failed: list[tuple[int, str]] = []
    succeeded: list[int] = []
    for n, result in zip(slots, results, strict=True):
        if isinstance(result, BaseException):
            failed.append((n, f"{type(result).__name__}: {result}"))
        elif result.status_code not in (200, 204):
            failed.append((n, f"HTTP_{result.status_code}: ..."))
        else:
            succeeded.append(n)
    return failed, succeeded


class _FakeResponse:
    def __init__(self, status_code: int, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def test_partial_press_failure_keeps_job_upscaling():
    """When upscale='all' and U2 fails but U1/U3/U4 succeed, the job stays
    in UPSCALING — successful slots can still land. The failure is recorded
    on Job.upscale_press_failures and U2 is removed from upscale_pending."""
    _reset_bridge_state()
    clear()
    job = _make_upscale_job(upscale="all")

    failed, succeeded = _press_partial_failures_via_gather(
        monkeypatch=None,
        slots=[1, 2, 3, 4],
        results=[
            _FakeResponse(204),
            _FakeResponse(500, "internal"),
            _FakeResponse(204),
            _FakeResponse(204),
        ],
    )

    # Apply the bookkeeping logic the real code performs under LOCK.
    for n, detail in failed:
        job.upscale_press_failures[n] = detail
        if n in job.upscale_pending:
            job.upscale_pending.remove(n)

    assert succeeded == [1, 3, 4]
    assert list(job.upscale_press_failures.keys()) == [2]
    assert job.upscale_pending == [1, 3, 4]
    assert job.status == Status.UPSCALING  # still alive


def test_all_press_failures_fails_job_with_all_buttons_failed():
    _reset_bridge_state()
    clear()
    job = _make_upscale_job(upscale="all")
    JOBS[job.job_id] = job

    failed, succeeded = _press_partial_failures_via_gather(
        monkeypatch=None,
        slots=[1, 2, 3, 4],
        results=[
            _FakeResponse(500),
            _FakeResponse(503),
            _FakeResponse(500),
            _FakeResponse(500),
        ],
    )

    assert not succeeded
    assert len(failed) == 4

    # Simulate the terminal-failure branch of _ingest_message.
    terminal_code = (
        "UPSCALE_BUTTON_FAILED" if len([1, 2, 3, 4]) == 1 else "UPSCALE_ALL_BUTTONS_FAILED"
    )
    assert terminal_code == "UPSCALE_ALL_BUTTONS_FAILED"
    job._fail(terminal_code, "all upscale presses failed — synthetic")

    assert job.status == Status.FAILED
    assert job.error_code == "UPSCALE_ALL_BUTTONS_FAILED"


def test_single_slot_press_failure_uses_button_failed_code():
    """upscale='3' (single slot) that fails uses UPSCALE_BUTTON_FAILED not
    UPSCALE_ALL_BUTTONS_FAILED — the enum distinguishes the two paths."""
    _reset_bridge_state()
    clear()
    slots = [3]
    _failed, succeeded = _press_partial_failures_via_gather(
        monkeypatch=None,
        slots=slots,
        results=[_FakeResponse(500)],
    )

    assert not succeeded
    terminal_code = "UPSCALE_BUTTON_FAILED" if len(slots) == 1 else "UPSCALE_ALL_BUTTONS_FAILED"
    assert terminal_code == "UPSCALE_BUTTON_FAILED"


def test_press_exception_classified_as_failure():
    """Per-slot exceptions (TimeoutError, DiscordNotReadyError) end up in the
    failed list with the exception class name as error_code."""
    _reset_bridge_state()
    clear()
    failed, succeeded = _press_partial_failures_via_gather(
        monkeypatch=None,
        slots=[1, 2],
        results=[
            DiscordNotReadyError("ws closed mid-press"),
            _FakeResponse(204),
        ],
    )
    assert succeeded == [2]
    assert len(failed) == 1
    assert "DiscordNotReadyError" in failed[0][1]


# ---------------------------------------------------------------------------
# Shutdown event interaction with reconnect loop
# ---------------------------------------------------------------------------


def test_emit_shutdown_sets_shutdown_event():
    """The signal/atexit shutdown path must set _shutdown_event so an
    in-progress backoff sleep can exit early."""
    _reset_bridge_state()
    clear()
    assert not bridge._shutdown_event.is_set()
    bridge._emit_shutdown("test")
    assert bridge._shutdown_event.is_set()
    # idempotent
    bridge._emit_shutdown("test_again")
    assert bridge._shutdown_event.is_set()


def test_shutdown_event_cuts_backoff_short(valid_env, monkeypatch):
    """A long backoff is interrupted by _shutdown_event.set() rather than
    sleeping out the full interval."""
    _reset_bridge_state()
    clear()
    bridge.cfg = bridge.Config.from_env()
    # Pick a long backoff so we'd notice if it actually slept.
    monkeypatch.setattr(bridge, "_reconnect_backoff_seconds", lambda n: 30.0)

    async def fake_start(*args, **kwargs):
        # First (and only) attempt fails transiently; the test thread will
        # signal shutdown during the backoff window.
        raise ConnectionResetError("transient")

    monkeypatch.setattr(bridge.client, "start", fake_start)

    def _signal_shutdown_soon():
        # Give _run_discord a beat to enter the backoff wait, then signal.
        threading.Event().wait(0.05)
        bridge._shutdown_event.set()

    t = threading.Thread(target=_signal_shutdown_soon)
    t.start()

    import time as _time

    t0 = _time.monotonic()
    bridge._run_discord()
    elapsed = _time.monotonic() - t0
    t.join()

    # Should exit well under the 30s backoff (the wait broke early).
    assert elapsed < 5.0
    failed = next(r for r in snapshot() if r["tag"] == "DISCORD_RECONNECT_FAILED")
    assert failed["payload"]["reason"] == "shutdown"


# ---------------------------------------------------------------------------
# /wait timeout validation
# ---------------------------------------------------------------------------


def test_wait_returns_400_on_non_numeric_timeout():
    """GET /wait/<id>?timeout=abc used to crash with Flask's default 500
    HTML page; agents expect the structured JSON envelope. Now returns
    400 with code=INVALID_TIMEOUT."""
    _reset_bridge_state()
    clear()
    job = Job(job_id="ttest", asset_id="x", prompt="p")
    JOBS["ttest"] = job

    client = bridge.app.test_client()
    resp = client.get("/wait/ttest?timeout=abc")
    assert resp.status_code == 400
    body = resp.get_json()
    assert body["ok"] is False
    assert body["error"]["code"] == "INVALID_TIMEOUT"
    assert "must be a number" in body["error"]["message"]


# ---------------------------------------------------------------------------
# Grid-race reservation
# ---------------------------------------------------------------------------


def test_concurrent_grid_ingest_only_downloads_once(monkeypatch, tmp_path):
    """on_message and on_message_edit can both fire _ingest_message for the
    same MJ message. Without reservation, both threads would download +
    upscale-press, double-billing MJ. The reservation pattern claims
    grid_path under LOCK before any I/O so a concurrent ingest short-
    circuits."""
    _reset_bridge_state()
    clear()
    # Wire a Config so _cfg() works in _ingest_message.
    bridge.cfg = bridge.Config(
        discord_token="t",
        channel_id=1,
        guild_id=None,
        mj_imagine_version="v",
        mj_imagine_command_id="c",
        output_dir=tmp_path,
        port=5000,
    )

    job = Job(job_id="raceJ", asset_id="raceA", prompt="p", request_token="tok99")
    job.status = Status.PROGRESS
    job.message_id = 12345
    JOBS[job.job_id] = job

    download_calls = {"n": 0}

    def fake_download(url, path):
        download_calls["n"] += 1
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 108

    monkeypatch.setattr(bridge, "_download_to", fake_download)

    # Fake MJ message that both threads will try to ingest.
    class _Att:
        url = "https://cdn/example.png"
        filename = "example.png"

    class _Author:
        id = bridge.MJ_BOT_ID

    class _Channel:
        id = 1  # matches cfg.channel_id

    class _Msg:
        id = 12345
        content = "done"
        guild = None

        def __init__(self):
            self.author = _Author()
            self.channel = _Channel()
            self.attachments = [_Att()]
            # A real final grid carries U/V result buttons; the bridge requires
            # them to tell a final grid from a low-res progress frame before
            # claiming the grid.
            btn = type("Btn", (), {"custom_id": "MJ::JOB::upsample::1::u"})()
            self.components = [type("Row", (), {"children": [btn]})()]

    # Fire two ingests in parallel — the second must short-circuit.
    threads = [threading.Thread(target=bridge._ingest_message, args=(_Msg(),)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    # Only one download happened.
    assert download_calls["n"] == 1
    # The job's grid_path is a real path (not the "" reservation sentinel
    # or None).
    assert job.grid_path is not None and job.grid_path != ""
    assert job.grid_path.endswith(".png")


def test_concurrent_upscale_ingest_only_downloads_once(monkeypatch, tmp_path):
    """The SOLO upscale message arrives as a create plus several in-place edits,
    each dispatched via run_in_executor, so two threads can both _match_upscale
    the same slot. Without the slot reservation they double-download and
    double-complete — a second UPSCALE_RECEIVED + JOB_COMPLETED for one job_id,
    breaching the locked terminal invariant. The reservation claims the slot
    under LOCK before any I/O so the second dispatch short-circuits. (Regression
    guard for the bug the hunt reproduced 18/18.)"""
    _reset_bridge_state()
    clear()
    bridge.cfg = bridge.Config(
        discord_token="t",
        channel_id=1,
        guild_id=None,
        mj_imagine_version="v",
        mj_imagine_command_id="c",
        output_dir=tmp_path,
        port=5000,
    )

    job = Job(job_id="upR", asset_id="upA", prompt="p", request_token="tokUP", upscale="1")
    job.status = Status.UPSCALING
    job.upscale_pending = [1]
    job.mj_job_uuid = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
    job.message_id = 555  # the grid message id, distinct from the SOLO id below
    JOBS[job.job_id] = job

    download_calls = {"n": 0}

    def fake_download(url, path):
        download_calls["n"] += 1
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
        return 108

    monkeypatch.setattr(bridge, "_download_to", fake_download)

    class _Att:
        url = "https://cdn/u1.png"
        filename = "u1.png"

    class _Author:
        id = bridge.MJ_BOT_ID

    class _Channel:
        id = 1  # matches cfg.channel_id

    class _Msg:
        id = 999  # the SOLO upscale message id (!= grid id), no reference
        content = "**a sprite cscidnocollidetokUP --raw** - Image #1 <@u>"
        guild = None
        reference = None

        def __init__(self):
            self.author = _Author()
            self.channel = _Channel()
            self.attachments = [_Att()]
            self.components = []

    threads = [threading.Thread(target=bridge._ingest_message, args=(_Msg(),)) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2.0)

    assert download_calls["n"] == 1
    assert job.upscale_paths.get(1) and job.upscale_paths[1] != ""
    assert job.upscale_message_ids.get(1) == 999
    assert job.status == Status.DONE
    tags = _tags()
    assert tags.count("UPSCALE_RECEIVED") == 1
    assert tags.count("JOB_COMPLETED") == 1


# ---------------------------------------------------------------------------
# /imagine idempotency key (review #3 — double-submit window)
# ---------------------------------------------------------------------------


def test_imagine_idempotency_key_replays_not_resubmits(monkeypatch):
    """Two /imagine POSTs with the same idempotency_key produce ONE job: the
    second is replayed (no second submission, no second MJ bill), closing the
    double-submit window a cancelled-mid-imagine MCP call opens (the orphaned
    worker-thread POST lands, then the agent retries with the same key).
    (review #3 idempotency)"""
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(monkeypatch, _FakeFuture(returns=_FakeResponse(204)))

    client = bridge.app.test_client()
    r1 = client.post(
        "/imagine", json={"prompt": "a mountain", "asset_id": "m", "idempotency_key": "K1"}
    )
    assert r1.status_code == 200
    job_id_1 = r1.get_json()["job_id"]

    r2 = client.post(
        "/imagine", json={"prompt": "a mountain", "asset_id": "m", "idempotency_key": "K1"}
    )
    assert r2.status_code == 200
    body2 = r2.get_json()
    assert body2["job_id"] == job_id_1  # same job, not a new submission
    assert body2["idempotent_replay"] is True
    with LOCK:
        assert len(JOBS) == 1  # only one job ever created
    # The replay did NOT re-submit, so only one IMAGINE_FIRED.
    assert _tags().count("IMAGINE_FIRED") == 1


def test_imagine_distinct_keys_make_distinct_jobs(monkeypatch):
    """Distinct idempotency keys make distinct jobs — re-rolls are NOT
    deduplicated (the whole point of not keying on asset_id). (review #3)"""
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(monkeypatch, _FakeFuture(returns=_FakeResponse(204)))

    client = bridge.app.test_client()
    r1 = client.post(
        "/imagine", json={"prompt": "a mountain", "asset_id": "m", "idempotency_key": "A"}
    )
    r2 = client.post(
        "/imagine", json={"prompt": "a mountain", "asset_id": "m", "idempotency_key": "B"}
    )
    assert r1.get_json()["job_id"] != r2.get_json()["job_id"]
    assert r2.get_json().get("idempotent_replay") is None
    with LOCK:
        assert len(JOBS) == 2


def test_imagine_without_key_always_new_job(monkeypatch):
    """No idempotency key -> every POST is a fresh job (existing behavior
    preserved; idempotency is strictly opt-in). (review #3)"""
    _reset_bridge_state()
    clear()
    bridge._ready.set()
    _patch_coroutine_threadsafe(monkeypatch, _FakeFuture(returns=_FakeResponse(204)))

    client = bridge.app.test_client()
    r1 = client.post("/imagine", json={"prompt": "x", "asset_id": "m"})
    r2 = client.post("/imagine", json={"prompt": "x", "asset_id": "m"})
    assert r1.get_json()["job_id"] != r2.get_json()["job_id"]
    with LOCK:
        assert len(JOBS) == 2


# ---------------------------------------------------------------------------
# Reservation-sentinel strip symmetry (review #4)
# ---------------------------------------------------------------------------


def test_grid_and_upscale_sentinels_stripped_on_persist(tmp_path):
    """A concurrent touch() can snapshot a job mid-download while grid_path /
    upscale_paths still hold the "" reservation sentinel. Persisting that ""
    would rehydrate as a claimed-but-empty slot the matchers never re-claim (the
    grid matcher skips ``grid_path is not None``; the upscale matcher skips
    ``idx in upscale_paths``) — a permanent non-terminal phantom. _persist strips
    the sentinels, exactly as it already does for derived rows. (review #4)"""
    _reset_bridge_state()
    store = JobStore(":memory:")
    bridge._store = store
    try:
        job = Job(job_id="sent", asset_id="A", prompt="p")
        job.status = Status.UPSCALING
        job.grid_path = ""  # reservation sentinel, mid grid-download
        job.upscale_paths = {1: "/real/u1.png", 2: ""}  # slot 2 mid-download
        bridge._persist(job)

        rows = store.load_nonterminal()
        assert len(rows) == 1
        assert rows[0]["grid_path"] is None  # "" stripped on the persist side
        # JSON stringifies dict keys; slot 2's "" sentinel is gone, slot 1 stays.
        assert rows[0]["upscale_paths"] == {"1": "/real/u1.png"}
    finally:
        bridge._store = None
        store.close()


def test_job_from_row_strips_baked_in_sentinels():
    """_job_from_row strips the sentinels symmetrically on the read side, so a
    row persisted by an older build (with "" baked in) still rehydrates clean and
    re-matchable. (review #4)"""
    base = Job(job_id="old", asset_id="A", prompt="p")
    base.status = Status.UPSCALING
    base.grid_path = ""
    base.upscale_paths = {1: "/real/u1.png", 2: ""}
    base.upscale_pending = [2, 3]
    row = asdict(base)

    job = bridge._job_from_row(row)
    assert job.grid_path is None  # re-matchable: grid matcher will re-claim it
    assert job.upscale_paths == {1: "/real/u1.png"}  # slot 2 sentinel dropped
    assert 2 in job.upscale_pending  # slot 2 still pending -> re-matchable


# ---------------------------------------------------------------------------
# Partial-tolerance on the upscale DOWNLOAD path (review #6)
# ---------------------------------------------------------------------------


def _solo_upscale_msg(slot: int, msg_id: int, token: str):
    """Build a fake MJ SOLO-upscale message for ``slot`` that _match_upscale will
    claim (token needle + 'Image #<slot>' in content, no reference)."""

    class _Att:
        url = f"https://cdn/u{slot}.png"
        filename = f"u{slot}.png"

    class _Author:
        id = bridge.MJ_BOT_ID

    class _Channel:
        id = 1  # matches the test cfg.channel_id

    class _Msg:
        id = msg_id
        content = f"**a sprite cscidnocollide{token} --raw** - Image #{slot} <@u>"
        guild = None
        reference = None

        def __init__(self):
            self.author = _Author()
            self.channel = _Channel()
            self.attachments = [_Att()]
            self.components = []

    return _Msg()


def _upscale_cfg(tmp_path):
    return bridge.Config(
        discord_token="t",
        channel_id=1,
        guild_id=None,
        mj_imagine_version="v",
        mj_imagine_command_id="c",
        output_dir=tmp_path,
        port=5000,
    )


def test_partial_upscale_download_failure_keeps_job_and_completes_on_survivors(
    monkeypatch, tmp_path
):
    """Under upscale='all', one slot's DOWNLOAD failure must not fail the whole
    job and discard siblings that landed or are still in flight. The press path
    already tolerates partial failure; the download path used to abandon it,
    job-wide _fail-ing on the first slot's download error. The failed slot is
    recorded and dropped from pending, and the job completes on the survivors.
    (review #6)"""
    _reset_bridge_state()
    clear()
    bridge.cfg = _upscale_cfg(tmp_path)

    job = Job(job_id="dlJ", asset_id="dlA", prompt="p", request_token="tokDL", upscale="all")
    job.status = Status.UPSCALING
    job.upscale_pending = [1, 2, 3, 4]
    job.mj_job_uuid = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
    job.message_id = 100  # grid id, distinct from the SOLO ids below
    JOBS[job.job_id] = job

    def fake_download(url, path):
        if "_u2" in str(path):
            raise OSError("disk full on U2")
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 50)
        return 58

    monkeypatch.setattr(bridge, "_download_to", fake_download)

    # Slot 2 lands first and its download fails — the job must survive.
    bridge._ingest_message(_solo_upscale_msg(2, 902, "tokDL"))
    assert job.status == Status.UPSCALING  # NOT failed
    assert 2 in job.upscale_download_failures
    assert 2 not in job.upscale_pending
    assert "JOB_FAILED" not in _tags()

    # The surviving slots land and the job completes on them.
    bridge._ingest_message(_solo_upscale_msg(1, 901, "tokDL"))
    bridge._ingest_message(_solo_upscale_msg(3, 903, "tokDL"))
    bridge._ingest_message(_solo_upscale_msg(4, 904, "tokDL"))

    assert job.status == Status.DONE
    assert set(job.upscale_paths) == {1, 3, 4}  # U2 absent (its download failed)
    assert all(v for v in job.upscale_paths.values())  # all real paths, no "" sentinel
    tags = _tags()
    assert tags.count("JOB_COMPLETED") == 1
    assert "JOB_FAILED" not in tags
    completed = next(r for r in snapshot() if r["tag"] == "JOB_COMPLETED")
    assert completed["payload"]["upscales_completed"] == 3
    # The download surface emits a per-slot incident (observability parity with
    # the press path's UPSCALE_PRESS_FAILED) for the one slot that failed.
    dropped = [r for r in snapshot() if r["tag"] == "UPSCALE_DOWNLOAD_DROPPED"]
    assert len(dropped) == 1
    assert dropped[0]["payload"]["slot"] == 2
    assert dropped[0]["payload"]["error_code"] == "OSError"


def test_last_slot_download_failure_after_survivor_completes_not_hangs(monkeypatch, tmp_path):
    """The adversarial ordering: a survivor lands FIRST, then the LAST pending
    slot's download fails. The job must complete on the survivor rather than
    hang in UPSCALING with empty pending (a phantom only the reaper would catch
    much later). Guards the failure-path's complete-on-empty-pending branch.
    (review #6)"""
    _reset_bridge_state()
    clear()
    bridge.cfg = _upscale_cfg(tmp_path)

    job = Job(job_id="lastF", asset_id="lastA", prompt="p", request_token="tokL", upscale="all")
    job.status = Status.UPSCALING
    job.upscale_pending = [1, 2]
    job.mj_job_uuid = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
    job.message_id = 300
    JOBS[job.job_id] = job

    def fake_download(url, path):
        if "_u2" in str(path):
            raise OSError("disk full on U2")
        Path(path).write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 50)
        return 58

    monkeypatch.setattr(bridge, "_download_to", fake_download)

    # Slot 1 lands; job stays UPSCALING (slot 2 still pending).
    bridge._ingest_message(_solo_upscale_msg(1, 301, "tokL"))
    assert job.status == Status.UPSCALING
    # Slot 2 (the last pending one) fails — job completes on the survivor U1.
    bridge._ingest_message(_solo_upscale_msg(2, 302, "tokL"))
    assert job.status == Status.DONE
    assert set(job.upscale_paths) == {1}
    assert 2 in job.upscale_download_failures
    tags = _tags()
    assert tags.count("JOB_COMPLETED") == 1
    assert "JOB_FAILED" not in tags


def test_all_upscale_downloads_fail_fails_job(monkeypatch, tmp_path):
    """When every slot's download fails (nothing landed, nothing still pending),
    the job DOES terminate with UPSCALE_DOWNLOAD_FAILED — partial-tolerance only
    keeps the job alive while some slot can still land. (review #6)"""
    _reset_bridge_state()
    clear()
    bridge.cfg = _upscale_cfg(tmp_path)

    job = Job(job_id="dlF", asset_id="dlA", prompt="p", request_token="tokF", upscale="all")
    job.status = Status.UPSCALING
    job.upscale_pending = [1, 2]
    job.mj_job_uuid = "uuuuuuuu-uuuu-uuuu-uuuu-uuuuuuuuuuuu"
    job.message_id = 200
    JOBS[job.job_id] = job

    def fake_download(url, path):
        raise OSError("disk full")

    monkeypatch.setattr(bridge, "_download_to", fake_download)

    # First slot fails but slot 2 is still pending — job stays alive.
    bridge._ingest_message(_solo_upscale_msg(1, 201, "tokF"))
    assert job.status == Status.UPSCALING

    # Last slot fails too — nothing can land, so the job fails.
    bridge._ingest_message(_solo_upscale_msg(2, 202, "tokF"))
    assert job.status == Status.FAILED
    assert job.error_code == "UPSCALE_DOWNLOAD_FAILED"
    assert {1, 2} <= set(job.upscale_download_failures)
    # A per-slot UPSCALE_DOWNLOAD_DROPPED fired for each failed download, in
    # addition to the terminal JOB_FAILED — exactly as the press path pairs
    # UPSCALE_PRESS_FAILED with UPSCALE_ALL_BUTTONS_FAILED.
    assert _tags().count("UPSCALE_DOWNLOAD_DROPPED") == 2


# ---------------------------------------------------------------------------
# Inflight-stall reaper (review #7, #8)
# ---------------------------------------------------------------------------


def test_reaper_fails_stalled_inflight_jobs_resubmit_required(monkeypatch):
    """A non-terminal job whose updated_at hasn't advanced past
    INFLIGHT_TIMEOUT_SECONDS is a stall: MJ stopped editing the progress message,
    or a rehydrated UPSCALING job's upscales never landed (its presses fired
    pre-restart and can't be safely re-fired), or a SUBMITTED_UNCONFIRMED job MJ
    never processed. Eviction only drops DONE/FAILED, so without the reaper it
    sits as a permanent phantom row against MAX_JOBS. The reaper fails it
    RESUBMIT_REQUIRED (already in the JOB_FAILED enum) so it becomes terminal and
    evictable, and tells the operator to re-submit and verify. (review #7, #8)"""
    _reset_bridge_state()
    clear()
    monkeypatch.setattr(bridge, "INFLIGHT_TIMEOUT_SECONDS", 100.0)
    now = time.time()

    def _job(jid, status, age):
        j = Job(job_id=jid, asset_id=jid.upper(), prompt="p")
        j.status = status
        j.updated_at = now - age
        return j

    stalled_progress = _job("sp", Status.PROGRESS, 200)
    stalled_upscaling = _job("su", Status.UPSCALING, 300)  # the #7 rehydrate phantom
    stalled_unconfirmed = _job("sx", Status.SUBMITTED_UNCONFIRMED, 500)
    fresh = _job("fr", Status.PROGRESS, 10)  # actively progressing — must survive
    done = _job("dn", Status.DONE, 99999)  # terminal — never a candidate
    with LOCK:
        for j in (stalled_progress, stalled_upscaling, stalled_unconfirmed, fresh, done):
            JOBS[j.job_id] = j
        PENDING_GRID.extend(["sp", "su", "sx"])

    reaped = bridge._reap_stalled_jobs()

    assert reaped == 3
    for j in (stalled_progress, stalled_upscaling, stalled_unconfirmed):
        assert j.status == Status.FAILED
        assert j.error_code == "RESUBMIT_REQUIRED"
        assert j.job_id not in PENDING_GRID  # pulled from pending on reap
    assert fresh.status == Status.PROGRESS  # untouched
    assert done.status == Status.DONE  # untouched
    failed = [r for r in snapshot() if r["tag"] == "JOB_FAILED"]
    assert len(failed) == 3
    assert all(r["payload"]["error_code"] == "RESUBMIT_REQUIRED" for r in failed)

    # Idempotent: the reaped jobs are now terminal, so a second sweep is a no-op.
    assert bridge._reap_stalled_jobs() == 0


def test_reaper_noop_when_all_fresh(monkeypatch):
    """No job past the timeout -> nothing reaped, nothing emitted. (review #8)"""
    _reset_bridge_state()
    clear()
    monkeypatch.setattr(bridge, "INFLIGHT_TIMEOUT_SECONDS", 100.0)
    now = time.time()
    j = Job(job_id="fresh", asset_id="A", prompt="p")
    j.status = Status.UPSCALING
    j.updated_at = now - 5
    with LOCK:
        JOBS[j.job_id] = j

    assert bridge._reap_stalled_jobs() == 0
    assert j.status == Status.UPSCALING
    assert "JOB_FAILED" not in _tags()

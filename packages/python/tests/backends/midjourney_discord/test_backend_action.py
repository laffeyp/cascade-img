"""Contract for MidjourneyDiscordBackend.action — the client-side unwrap.

The bridge's POST /action already speaks the {ok, result | error} envelope, so
the backend must UNWRAP it: return the bare result on success, raise
BridgeActionError on failure. Without this, _run_tool would double-wrap into
{ok: true, result: {ok: false, ...}} — a contract violation the MCP-level fake
backend is structurally blind to (it stands in for this method). This is the
test seam at the right layer: it exercises the real r.json() handling.
"""

from __future__ import annotations

import pytest

from cascade_img.backends.midjourney_discord import backend as bk


class _FakeResp:
    def __init__(self, payload, status=200, text=""):
        self._payload = payload
        self.status_code = status
        self.text = text

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def json(self):
        return self._payload


def test_action_unwraps_success_to_single_level(monkeypatch):
    result = {"job_id": "j", "action": "vary_strong", "custom_id": "c", "message_id": 1}
    monkeypatch.setattr(
        bk.requests, "post", lambda *a, **k: _FakeResp({"ok": True, "result": result})
    )
    out = bk.MidjourneyDiscordBackend().action("j", "vary_strong")
    # The bare result, NOT the {ok, result} envelope — so _run_tool wraps once.
    assert out == result


def test_action_raises_structured_error_on_failure(monkeypatch):
    monkeypatch.setattr(
        bk.requests,
        "post",
        lambda *a, **k: _FakeResp(
            {
                "ok": False,
                "error": {
                    "code": "NO_UPSCALED_IMAGE",
                    "message": "this action needs an upscaled image",
                    "remediation": "upscale a quadrant first",
                },
            },
            status=409,
        ),
    )
    with pytest.raises(bk.BridgeActionError) as ei:
        bk.MidjourneyDiscordBackend().action("j", "animate_high")
    assert ei.value.code == "NO_UPSCALED_IMAGE"
    assert ei.value.remediation == "upscale a quadrant first"


def test_action_failure_without_error_body_uses_http_status(monkeypatch):
    monkeypatch.setattr(
        bk.requests,
        "post",
        lambda *a, **k: _FakeResp({"ok": False}, status=502, text="bad gateway"),
    )
    with pytest.raises(bk.BridgeActionError) as ei:
        bk.MidjourneyDiscordBackend().action("j", "vary_strong")
    assert ei.value.code == "HTTP_502"


# imagine/wait/status/health must surface the bridge's stable code on failure
# (not flatten to a bare HTTPError) — the same contract as action().


def test_imagine_surfaces_bridge_code_and_remediation(monkeypatch):
    monkeypatch.setattr(
        bk.requests,
        "post",
        lambda *a, **k: _FakeResp(
            {
                "error": "discord not ready",
                "code": "DISCORD_NOT_READY",
                "remediation": "wait for reconnect",
            },
            status=503,
        ),
    )
    with pytest.raises(bk.BridgeError) as ei:
        bk.MidjourneyDiscordBackend().imagine("p", "a")
    assert ei.value.code == "DISCORD_NOT_READY"
    assert ei.value.remediation == "wait for reconnect"


def test_status_unknown_job_surfaces_http_code(monkeypatch):
    monkeypatch.setattr(
        bk.requests, "get", lambda *a, **k: _FakeResp({"error": "unknown job_id"}, status=404)
    )
    with pytest.raises(bk.BridgeError) as ei:
        bk.MidjourneyDiscordBackend().status("nope")
    assert ei.value.code == "HTTP_404"  # branchable, not "HTTPError"


def test_wait_504_returns_timed_out_without_raising(monkeypatch):
    monkeypatch.setattr(
        bk.requests,
        "get",
        lambda *a, **k: _FakeResp({"job_id": "j", "status": "progress"}, status=504),
    )
    out = bk.MidjourneyDiscordBackend().wait("j", timeout=1)
    assert out["timed_out"] is True

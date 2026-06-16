"""Contract for MidjourneyDiscordBackend.action — the client-side unwrap.

The bridge's POST /action already speaks the {ok, result | error} envelope, so
the backend must UNWRAP it: return the bare result on success, raise
BridgeActionError on failure. Without this, _run_tool would double-wrap into
{ok: true, result: {ok: false, ...}} — a contract violation the MCP-level fake
backend is structurally blind to (it stands in for this method). This test
exercises the real r.json() handling directly.
"""

from __future__ import annotations

import pytest

from cascade_img.backends.midjourney_discord import bridge_client as bk


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


def test_wait_504_with_non_json_body_returns_timed_out(monkeypatch):
    """A 504 from an intermediary (reverse proxy / LB) commonly carries an HTML
    body. wait() must still return timed_out=True rather than letting r.json()'s
    ValueError propagate — a caller would mistake that for a hard failure and
    lose the 'still rendering, poll, do NOT re-roll' semantics. (review bug-hunt)"""

    class _NonJsonResp:
        status_code = 504
        text = "<html>504 Gateway Timeout</html>"

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def json(self):
            raise ValueError("Expecting value: line 1 column 1 (char 0)")

    monkeypatch.setattr(bk.requests, "get", lambda *a, **k: _NonJsonResp())
    out = bk.MidjourneyDiscordBackend().wait("j", timeout=1)
    assert out == {"timed_out": True}


def test_imagine_sends_idempotency_key_in_body_when_given(monkeypatch):
    """backend.imagine threads idempotency_key into the POST body so the bridge
    can replay instead of double-submitting; it is omitted entirely when not
    given (idempotency strictly opt-in). (review #3)"""
    captured: dict = {}

    def _fake_post(url, json=None, timeout=None):
        captured["json"] = json
        return _FakeResp({"job_id": "j", "asset_id": "a", "status": "submitted"})

    monkeypatch.setattr(bk.requests, "post", _fake_post)
    be = bk.MidjourneyDiscordBackend()

    be.imagine("p", "a", idempotency_key="IDEM-9")
    assert captured["json"]["idempotency_key"] == "IDEM-9"

    be.imagine("p", "a")  # no key -> omitted
    assert "idempotency_key" not in captured["json"]


# --------------------- success + error branches across every method ---------


def test_imagine_success_includes_upscale_in_body(monkeypatch):
    """imagine threads upscale into the POST body and returns the bridge's
    ImagineResult unchanged on success."""
    captured: dict = {}

    def _post(url, json=None, timeout=None):
        captured["json"] = json
        return _FakeResp({"job_id": "j", "asset_id": "a", "status": "submitted", "upscale": "all"})

    monkeypatch.setattr(bk.requests, "post", _post)
    out = bk.MidjourneyDiscordBackend().imagine("p", "a", upscale="all")
    assert captured["json"]["upscale"] == "all"
    assert out["job_id"] == "j"


def test_wait_success_returns_job_state(monkeypatch):
    """A 200 wait returns the terminal job state verbatim (no timed_out injected)."""
    monkeypatch.setattr(
        bk.requests,
        "get",
        lambda *a, **k: _FakeResp({"job_id": "j", "status": "done", "image_path": "/tmp/x.png"}),
    )
    out = bk.MidjourneyDiscordBackend().wait("j", timeout=1)
    assert out["status"] == "done"
    assert "timed_out" not in out


def test_wait_4xx_raises_stable_code(monkeypatch):
    """A non-504 4xx during wait (e.g. job evicted mid-wait) raises BridgeError
    with the stable code, not a flattened HTTPError."""
    monkeypatch.setattr(
        bk.requests,
        "get",
        lambda *a, **k: _FakeResp({"error": "gone", "code": "JOB_EVICTED"}, status=410),
    )
    with pytest.raises(bk.BridgeError) as ei:
        bk.MidjourneyDiscordBackend().wait("j", timeout=1)
    assert ei.value.code == "JOB_EVICTED"


def test_wait_504_non_dict_json_body_returns_timed_out(monkeypatch):
    """A 504 whose JSON body parses to a non-dict (e.g. a list from a proxy)
    still yields timed_out=True rather than corrupting the JobState."""
    monkeypatch.setattr(
        bk.requests, "get", lambda *a, **k: _FakeResp(["unexpected", "list"], status=504)
    )
    out = bk.MidjourneyDiscordBackend().wait("j", timeout=1)
    assert out == {"timed_out": True}


def test_status_success_returns_state(monkeypatch):
    monkeypatch.setattr(
        bk.requests, "get", lambda *a, **k: _FakeResp({"job_id": "j", "status": "progress"})
    )
    out = bk.MidjourneyDiscordBackend().status("j")
    assert out["status"] == "progress"


def test_health_success_and_error(monkeypatch):
    monkeypatch.setattr(
        bk.requests, "get", lambda *a, **k: _FakeResp({"discord_ready": True, "total_jobs": 0})
    )
    assert bk.MidjourneyDiscordBackend().health()["discord_ready"] is True

    monkeypatch.setattr(
        bk.requests,
        "get",
        lambda *a, **k: _FakeResp({"error": "down", "code": "BRIDGE_DOWN"}, status=503),
    )
    with pytest.raises(bk.BridgeError) as ei:
        bk.MidjourneyDiscordBackend().health()
    assert ei.value.code == "BRIDGE_DOWN"


def test_action_threads_slot_into_body(monkeypatch):
    """action with slot=N puts it in the POST body (targets one SOLO under
    upscale='all'); omitting slot leaves it out."""
    captured: dict = {}

    def _post(url, json=None, timeout=None):
        captured["json"] = json
        return _FakeResp({"ok": True, "result": {"job_id": "j", "action": "vary_strong"}})

    monkeypatch.setattr(bk.requests, "post", _post)
    bk.MidjourneyDiscordBackend().action("j", "vary_strong", slot=3)
    assert captured["json"] == {"action": "vary_strong", "slot": 3}


def test_raise_for_envelope_non_dict_body_falls_back_to_http_status(monkeypatch):
    """A non-dict JSON error body (a list/scalar from an intermediary) cannot
    carry a code, so the stable code falls back to HTTP_<status>."""
    with pytest.raises(bk.BridgeError) as ei:
        bk._raise_for_envelope(_FakeResp(["not", "a", "dict"], status=500))
    assert ei.value.code == "HTTP_500"

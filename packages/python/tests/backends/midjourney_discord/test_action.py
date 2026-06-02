"""Behavior contract for Wave F response-message actions (vary / zoom / pan /
upscale-variant / animate / favorite) — the submit side.

Two layers, no live Discord:
  - ``_find_action_custom_id`` reads the *live* button id off a message by its
    captured stable marker; this is the core "never hardcode the uuid" logic.
  - ``POST /action/<job_id>`` validation, driven through Flask's test client,
    covering the four guard paths that resolve before any Discord call.
"""

from __future__ import annotations

from cascade_img.backends.midjourney_discord import bridge
from cascade_img.backends.midjourney_discord.bridge import (
    _ACTION_MARKERS,
    JOBS,
    LOCK,
    Job,
    Status,
    _find_action_custom_id,
)
from cascade_img.vocabulary import clear, snapshot


def _reset_jobs():
    with LOCK:
        JOBS.clear()
        bridge.PENDING_GRID.clear()


def _tags() -> list[str]:
    return [r["tag"] for r in snapshot()]


# ---- a fake SOLO upscaled-image message mirroring the captured button set ----


class _Btn:
    def __init__(self, custom_id):
        self.custom_id = custom_id


class _Row:
    def __init__(self, children):
        self.children = children


class _Msg:
    def __init__(self, rows):
        self.components = rows


def _solo_message(uuid="abc123"):
    """The button surface MJ attaches to a SOLO upscaled image (captured
    2026-06-02). One row is plenty for the finder — it walks all rows/children."""
    cids = [
        f"MJ::JOB::upsample_v7_2x_subtle::1::{uuid}::SOLO",
        f"MJ::JOB::upsample_v7_2x_creative::1::{uuid}::SOLO",
        f"MJ::JOB::low_variation::1::{uuid}::SOLO",
        f"MJ::JOB::high_variation::1::{uuid}::SOLO",
        f"MJ::Outpaint::50::1::{uuid}::SOLO",
        f"MJ::Outpaint::75::1::{uuid}::SOLO",
        f"MJ::JOB::pan_left::1::{uuid}::SOLO",
        f"MJ::JOB::pan_right::1::{uuid}::SOLO",
        f"MJ::JOB::pan_up::1::{uuid}::SOLO",
        f"MJ::JOB::pan_down::1::{uuid}::SOLO",
        f"MJ::JOB::animate_high::1::{uuid}::SOLO",
        f"MJ::JOB::animate_low::1::{uuid}::SOLO",
        f"MJ::BOOKMARK::{uuid}",
    ]
    return _Msg([_Row([_Btn(c) for c in cids])])


# ---------------- the finder ----------------


def test_find_action_custom_id_returns_live_id_for_every_action():
    """Each action resolves to the full live custom_id (uuid embedded), read off
    the component — not a reconstruction. Every marker in the map must match."""
    msg = _solo_message("deadbeef")
    for action in _ACTION_MARKERS:
        cid = _find_action_custom_id(msg, action)
        assert cid is not None, f"{action} should have matched"
        assert "deadbeef" in cid  # the live uuid came back, not the marker


def test_find_action_custom_id_disambiguates_paired_buttons():
    """The lookalike pairs must not cross-match: subtle≠creative,
    low≠high variation, Outpaint::50≠::75."""
    msg = _solo_message("u1")
    assert (
        _find_action_custom_id(msg, "upscale_subtle")
        == "MJ::JOB::upsample_v7_2x_subtle::1::u1::SOLO"
    )
    assert (
        _find_action_custom_id(msg, "upscale_creative")
        == "MJ::JOB::upsample_v7_2x_creative::1::u1::SOLO"
    )
    assert _find_action_custom_id(msg, "vary_subtle") == "MJ::JOB::low_variation::1::u1::SOLO"
    assert _find_action_custom_id(msg, "vary_strong") == "MJ::JOB::high_variation::1::u1::SOLO"
    assert _find_action_custom_id(msg, "zoom_out_2x") == "MJ::Outpaint::50::1::u1::SOLO"
    assert _find_action_custom_id(msg, "zoom_out_1_5x") == "MJ::Outpaint::75::1::u1::SOLO"


def test_find_action_custom_id_absent_button_returns_none():
    """A message lacking the button yields None so the caller reports
    BUTTON_NOT_FOUND rather than pressing the wrong control."""
    msg = _Msg([_Row([_Btn("MJ::JOB::high_variation::1::x::SOLO")])])
    assert _find_action_custom_id(msg, "zoom_out_2x") is None
    assert _find_action_custom_id(msg, "animate_high") is None


def test_action_markers_match_the_locked_action_enum():
    """The marker map's keys are the canonical action set; they must equal the
    enum the vocabulary constrains MJ_ACTION_REQUESTED.action to."""
    expected = {
        "upscale_subtle",
        "upscale_creative",
        "vary_subtle",
        "vary_strong",
        "zoom_out_2x",
        "zoom_out_1_5x",
        "pan_left",
        "pan_right",
        "pan_up",
        "pan_down",
        "animate_high",
        "animate_low",
        "favorite",
    }
    assert set(_ACTION_MARKERS) == expected


# ---------------- POST /action/<job_id> guard paths ----------------


def test_action_unknown_action_returns_400():
    """Validated before any Discord work — no cfg/ready needed."""
    client = bridge.app.test_client()
    r = client.post("/action/whatever", json={"action": "bogus"})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "UNKNOWN_ACTION"


def test_action_not_ready_returns_503():
    bridge._ready.clear()
    client = bridge.app.test_client()
    r = client.post("/action/whatever", json={"action": "vary_strong"})
    assert r.status_code == 503
    assert r.get_json()["error"]["code"] == "DISCORD_NOT_READY"


def test_action_unknown_job_returns_404():
    _reset_jobs()
    bridge._ready.set()
    try:
        client = bridge.app.test_client()
        r = client.post("/action/nope", json={"action": "vary_strong"})
        assert r.status_code == 404
        assert r.get_json()["error"]["code"] == "UNKNOWN_JOB"
    finally:
        bridge._ready.clear()


def test_action_no_upscaled_image_returns_409_and_emits_failure():
    """A job with no upscaled image can't be acted on — the buttons live on a
    SOLO upscale. Emits MJ_ACTION_FAILED(NO_UPSCALED_IMAGE)."""
    _reset_jobs()
    bridge._ready.set()
    clear()
    try:
        job = Job(job_id="j-grid", asset_id="bird", prompt="a finch", status=Status.DONE)
        with LOCK:
            JOBS["j-grid"] = job
        client = bridge.app.test_client()
        r = client.post("/action/j-grid", json={"action": "animate_high"})
        assert r.status_code == 409
        assert r.get_json()["error"]["code"] == "NO_UPSCALED_IMAGE"
        assert "MJ_ACTION_FAILED" in _tags()
    finally:
        bridge._ready.clear()
        _reset_jobs()

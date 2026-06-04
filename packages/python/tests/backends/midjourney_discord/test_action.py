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
    MJ_BOT_ID,
    Job,
    Status,
    _classify_derived,
    _find_action_custom_id,
    _has_result_button,
    _ingest_message,
    _job_by_upscale_message_id,
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
        job = Job(
            job_id="j-grid", asset_id="mountain-icon", prompt="a mountain", status=Status.DONE
        )
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


# ---------------- receive side (derived results) ----------------
#
# Fixtures below mirror a verbatim 2026-06-02 live capture (SOLO message id
# 1511317210822611026, parent uuid bb5d727b...). The routing key under test is
# message_reference == the SOLO id; nothing here is guessed.

_SOLO_ID = 1511317210822611026


class _Att:
    def __init__(self, filename, content_type="image/webp", width=2048, height=2048, size=1):
        self.filename = filename
        self.url = f"https://cdn.discordapp.com/attachments/x/y/{filename}"
        self.content_type = content_type
        self.width = width
        self.height = height
        self.size = size
        self.duration = None


class _Ref:
    def __init__(self, message_id):
        self.message_id = message_id


class _DMsg:
    """A Midjourney message fake carrying the fields the derived-result path
    reads: author/channel (so _ingest_message accepts it), reference, content,
    attachments, and flattened button components."""

    def __init__(self, mid, content, ref_id=None, attachments=None, button_cids=None, channel_id=1):
        self.id = mid
        self.content = content
        self.reference = _Ref(ref_id) if ref_id is not None else None
        self.attachments = attachments or []
        cids = button_cids or []
        self.components = [_Row([_Btn(c) for c in cids])] if cids else []
        self.author = type("A", (), {"id": MJ_BOT_ID})()
        self.channel = type("C", (), {"id": channel_id})()
        self.created_at = None
        self.edited_at = None


def _vary_final():
    # raw-capture line 37
    return _DMsg(
        1511317624292769933,
        "**a small bird ... cscidnocollide781b1185 --raw** - Variations (Strong) by <@1502242966100639815> "
        "[(Open on website)](<https://midjourney.com/jobs/9a5aa072-26f3-4902-a2e2-f76f2db12270>) (fast)",
        ref_id=_SOLO_ID,
        attachments=[_Att("u2233346927_..._9a5aa072-26f3-4902-a2e2-f76f2db12270.webp")],
        button_cids=["MJ::JOB::upsample::1::9a5aa072-26f3-4902-a2e2-f76f2db12270"],
    )


def _animate_final():
    # raw-capture line 85 — animated webp, NOT mp4
    return _DMsg(
        1511319451277201564,
        "**a small bird ... --raw --motion high --video 1 --aspect 1:1** - <@1502242966100639815> "
        "[(Open on website)](<https://midjourney.com/jobs/9bdd338a-3876-4b4b-b175-af661e8a8cab>) (fast)",
        ref_id=_SOLO_ID,
        attachments=[
            _Att("u2233346927_..._9bdd338a-3876-4b4b-b175-af661e8a8cab.webp", width=624, height=624)
        ],
        button_cids=["MJ::JOB::video_virtual_upscale::1::9bdd338a-3876-4b4b-b175-af661e8a8cab"],
    )


def _make_parent(monkeypatch, tmp_path):
    """A DONE parent job with a recorded SOLO message, plus cfg + a stubbed
    downloader so _ingest_derived runs without a live Discord/CDN."""
    _reset_jobs()
    clear()
    cfg = bridge.Config(
        discord_token="t",
        channel_id=1,
        guild_id=None,
        mj_imagine_version="v",
        mj_imagine_command_id="c",
        output_dir=tmp_path,
        port=5057,
    )
    monkeypatch.setattr(bridge, "cfg", cfg)
    parent = Job(job_id="p1", asset_id="livebird", prompt="a small bird", status=Status.DONE)
    parent.upscale_message_id = _SOLO_ID
    with LOCK:
        JOBS["p1"] = parent
    return parent


def test_classify_derived_covers_every_family():
    assert _classify_derived("...--raw** - Variations (Strong) by <@x>") == "variation"
    assert _classify_derived("...--raw** - Zoom Out by <@x>") == "zoom"
    assert _classify_derived("...--ar 3:2** - Pan Right by <@x>") == "pan"
    assert _classify_derived("...--raw** - Upscaled by <@x>") == "upscale"
    assert (
        _classify_derived("**a bird --raw --motion high --video 1 --aspect 1:1** - <@x>")
        == "animation"
    )
    # A user who wrote --video in their /imagine prompt: a vary/zoom/pan/upscale
    # echo carries --video inside the bolded prompt but NOT MJ's --motion
    # video-rewrite marker, so it must stay "variation", not flip to "animation".
    assert (
        _classify_derived(
            "**a cat --video --ar 16:9 --no cscidnocollidetok** - Variations (Strong) by <@x>"
        )
        == "variation"
    )


def test_has_result_button_distinguishes_final_from_progress():
    final = _DMsg(1, "x", attachments=[_Att("f.webp")], button_cids=["MJ::JOB::upsample::1::u"])
    progress = _DMsg(
        2,
        "x (35%)",
        attachments=[_Att("p.webp", width=512, height=512)],
        button_cids=["MJ::CancelJob::ByJobid::u"],
    )
    frame = _DMsg(
        3, "x", attachments=[_Att("s.jpg", content_type="image/jpeg", width=256, height=256)]
    )
    assert _has_result_button(final) is True
    assert _has_result_button(progress) is False  # Cancel-only is not a result
    assert _has_result_button(frame) is False  # bare progress frame, no buttons


def test_derived_result_routes_to_parent_and_emits(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_download_to", lambda url, path: 295714)
    _ingest_message(_vary_final())
    assert len(parent.derived) == 1
    d = parent.derived[0]
    assert d["action_kind"] == "variation"
    assert d["mj_uuid"] == "9a5aa072-26f3-4902-a2e2-f76f2db12270"  # the NEW uuid, off the filename
    assert d["bytes"] == 295714 and d["path"].endswith(".webp")
    tags = _tags()
    assert "MJ_DERIVED_RECEIVED" in tags


def test_derived_animation_is_classified_and_downloaded(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_download_to", lambda url, path: 2496346)
    _ingest_message(_animate_final())
    assert len(parent.derived) == 1
    d = parent.derived[0]
    assert d["action_kind"] == "animation"
    assert d["content_type"] == "image/webp"  # observed: animated webp, NOT video/mp4
    assert d["mj_uuid"] == "9bdd338a-3876-4b4b-b175-af661e8a8cab"


def test_derived_claimed_once_across_edits(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    calls = {"n": 0}

    def _count(url, path):
        calls["n"] += 1
        return 295714

    monkeypatch.setattr(bridge, "_download_to", _count)
    msg = _vary_final()
    _ingest_message(msg)
    _ingest_message(msg)  # a later edit of the same final re-enters
    assert calls["n"] == 1
    assert len(parent.derived) == 1


def test_favorite_confirmation_produces_no_artifact(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_download_to", lambda url, path: 1)
    # raw-capture line 86: references the SOLO but has no attachment / no buttons.
    fav = _DMsg(
        1511319783969263847,
        "You have successfully rated [this job](https://discord.com/channels/g/c/1511317210822611026) with the heart-eyes emoji",
        ref_id=_SOLO_ID,
    )
    _ingest_message(fav)
    assert parent.derived == []
    assert "MJ_DERIVED_RECEIVED" not in _tags()


def test_progress_frame_is_not_downloaded(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_download_to", lambda url, path: 1)
    # raw-capture line 33-style: references SOLO, has a low-res preview, but only
    # a Cancel button and a "(35%)" marker — must not be taken for the final.
    progress = _DMsg(
        1511317524300697661,
        "**a small bird ... cscidnocollide781b1185 --raw** - Variations (Strong) by <@x> (35%) (fast)",
        ref_id=_SOLO_ID,
        attachments=[_Att("9a5aa072_grid_0.webp", width=512, height=512)],
        button_cids=["MJ::CancelJob::ByJobid::9a5aa072-26f3-4902-a2e2-f76f2db12270"],
    )
    _ingest_message(progress)
    assert parent.derived == []


def test_foreign_job_result_is_not_misrouted(tmp_path, monkeypatch):
    """The capture proved a foreign job interleaved into the channel. Its result
    references its OWN solo id, not ours — the reference key must exclude it."""
    parent = _make_parent(monkeypatch, tmp_path)
    monkeypatch.setattr(bridge, "_download_to", lambda url, path: 12483848)
    # raw-capture line 45: foreign animate, references the foreign solo 1511317460668780624.
    foreign = _DMsg(
        1511318740325346068,
        "**a classic 2000s mobile game scene --motion high --video 1 --aspect 1:1** - <@x>",
        ref_id=1511317460668780624,
        attachments=[_Att("..._564950e3.webp", width=624, height=624)],
        button_cids=["MJ::JOB::video_virtual_upscale::1::564950e3-461a-45ca-9aac-c9fd4ddd1e50"],
    )
    _ingest_message(foreign)
    assert parent.derived == []
    assert _job_by_upscale_message_id(1511317460668780624) is None


def test_job_by_upscale_message_id_matches_the_solo(tmp_path, monkeypatch):
    parent = _make_parent(monkeypatch, tmp_path)
    assert _job_by_upscale_message_id(_SOLO_ID) is parent
    assert _job_by_upscale_message_id(999) is None

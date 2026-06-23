"""Native video path: bind-on-vendor-echo routing (F34) + the ingest lifecycle
that downloads the animated webp and emits VIDEO_RECEIVED / VIDEO_FAILED.

Models the real result shape captured live by tools/mj_capture_video.py
(2026-06-15): MJ's first ack carries a `s.mj.run/XXX` short URL + `--video`
(there is no `--no` token to route on); progress frames carry that URL + a `%`
and no result buttons; the final is one `.webp` on a message bearing
`video_virtual_upscale` buttons.
"""

from __future__ import annotations

from pathlib import Path

from cascade_img.backends.midjourney_discord import bridge, config
from cascade_img.backends.midjourney_discord.ingest import matching
from cascade_img.backends.midjourney_discord.ingest import messages as ingest
from cascade_img.backends.midjourney_discord.jobs.job import Job, Status
from cascade_img.backends.midjourney_discord.jobs.job_table import (
    JOBS,
    LOCK,
    PENDING_GRID,
    PENDING_VIDEO,
)
from cascade_img.backends.midjourney_discord.transport import discord_parse, runtime
from cascade_img.vocabulary import clear, snapshot

SHORT = "https://s.mj.run/alB1cz6cskw"


def _reset():
    with LOCK:
        JOBS.clear()
        PENDING_GRID.clear()
        PENDING_VIDEO.clear()


def _tags():
    return [r["tag"] for r in snapshot()]


def _cfg(tmp_path):
    return bridge.Config(
        discord_token="t",
        channel_id=1,
        guild_id=None,
        mj_imagine_version="v",
        mj_imagine_command_id="c",
        output_dir=tmp_path,
        port=5000,
    )


class _Author:
    id = config.MJ_BOT_ID


class _Channel:
    id = 1


def _vid_msg(msg_id: int, content: str, *, atts=None, buttons=None, ref_id=None):
    """A fake MJ video message: content + optional attachments + optional
    result-button custom_ids + optional message_reference (for derived replies).
    An attachment ending .mp4 is typed video/mp4, .webp -> image/webp, else jpeg."""

    class _Att:
        def __init__(self, url, filename):
            self.url = url
            self.filename = filename
            if filename.endswith(".mp4"):
                self.content_type = "video/mp4"
            elif filename.endswith(".webp"):
                self.content_type = "image/webp"
            else:
                self.content_type = "image/jpeg"
            self.size = 1234

    class _Btn:
        def __init__(self, cid):
            self.custom_id = cid

    class _Row:
        def __init__(self, kids):
            self.children = kids

    class _Ref:
        def __init__(self, mid):
            self.message_id = mid

    class _Msg:
        id = msg_id
        guild = None

        def __init__(self):
            self.content = content
            self.author = _Author()
            self.channel = _Channel()
            self.attachments = [_Att(u, f) for (u, f) in (atts or [])]
            self.components = [_Row([_Btn(c) for c in buttons])] if buttons else []
            self.reference = _Ref(ref_id) if ref_id is not None else None

    return _Msg()


_ACK = f"Creating video with prompt **<{SHORT}> --end loop --video 1 --aspect 1:1** - <@u> (Waiting to start)"
_PROGRESS = f"**<{SHORT}> --end loop --video 1 --aspect 1:1** - <@u> (35%) (fast)"
_FINAL = f"**<{SHORT}> --end loop --video 1 --aspect 1:1** - <@u> [(Open on website)](x) (fast)"
_FINAL_BTNS = [
    "MJ::JOB::video_virtual_upscale::1::35d26bdd-2443-4435-8a31-57da30edcd62",
    "MJ::JOB::reroll::0::35d26bdd-2443-4435-8a31-57da30edcd62::SOLO",
]


# --------------------------- _match_video (F34) ---------------------------


def test_match_video_binds_on_ack_then_matches_by_key():
    """The first ack (has a short URL + --video) binds the oldest PENDING_VIDEO
    job to that URL; subsequent messages match on the bound key."""
    _reset()
    job = Job(job_id="v1", asset_id="a", prompt=f"{SHORT} --video --loop", kind="video")
    JOBS[job.job_id] = job
    PENDING_VIDEO.append(job.job_id)

    bound = matching._match_video(_ACK)
    assert bound is job
    assert job.video_match_key == SHORT
    assert not PENDING_VIDEO  # consumed
    # progress + final now route by the bound key
    assert matching._match_video(_PROGRESS) is job
    assert matching._match_video(_FINAL) is job


def test_match_video_ignores_non_video_and_unbound():
    _reset()
    job = Job(job_id="v2", asset_id="a", prompt="p", kind="video")
    JOBS[job.job_id] = job
    PENDING_VIDEO.append(job.job_id)
    # An s.mj.run link without --video must not bind (not a video echo).
    assert matching._match_video(f"some message <{SHORT}> no video flag") is None
    assert job.video_match_key is None
    assert len(PENDING_VIDEO) == 1 and PENDING_VIDEO[0] == job.job_id  # still unbound


# --------------------------- ingest lifecycle ---------------------------


def test_video_ingest_downloads_webp_and_completes(monkeypatch, tmp_path):
    """Ack -> progress -> final-webp drives the job to DONE with VIDEO_RECEIVED
    (not GRID_RECEIVED) and the webp saved as the result image."""
    _reset()
    clear()
    config.cfg = _cfg(tmp_path)

    def fake_download(url, path):
        Path(path).write_bytes(b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"x" * 64)
        return 80

    monkeypatch.setattr(discord_parse, "_download_to", fake_download)

    job = Job(job_id="vj", asset_id="vid", prompt=f"{SHORT} --video --loop", kind="video")
    JOBS[job.job_id] = job
    PENDING_VIDEO.append(job.job_id)

    ingest._ingest_message(_vid_msg(700, _ACK))  # binds + PROGRESS
    assert job.video_match_key == SHORT
    assert job.status == Status.PROGRESS

    # progress frame: short URL + % + jpeg previews, NO result buttons -> skipped
    ingest._ingest_message(_vid_msg(701, _PROGRESS, atts=[("https://cdn/p0.jpeg", "p0.jpeg")]))
    assert job.status == Status.PROGRESS
    assert job.grid_path in (None, "")

    # final: webp + video_virtual_upscale buttons, REPLYING to the progress
    # message (ref_id=701, the job's current message_id) — as real MJ does. This
    # must COMPLETE the job (VIDEO_RECEIVED), not be hijacked into `derived` by
    # _video_result_parent (which only matches DONE jobs). (regression, live 06-16)
    ingest._ingest_message(
        _vid_msg(
            702,
            _FINAL,
            atts=[("https://cdn/final.webp", "v_uuid.webp")],
            buttons=_FINAL_BTNS,
            ref_id=701,
        )
    )
    assert job.status == Status.DONE
    assert job.image_path and job.image_path.endswith(".webp")
    assert Path(job.image_path).exists()
    assert job.derived == []  # the job's OWN result completed it, not routed to derived
    tags = _tags()
    assert "VIDEO_RECEIVED" in tags
    assert "JOB_COMPLETED" in tags
    assert "GRID_RECEIVED" not in tags  # honest signal: it's a video, not a grid


def test_video_download_failure_emits_video_failed(monkeypatch, tmp_path):
    """A failed webp download fails the video job through VIDEO_FAILED (not the
    generic JOB_FAILED) with the video error code."""
    _reset()
    clear()
    config.cfg = _cfg(tmp_path)

    def boom(url, path):
        raise OSError("disk full")

    monkeypatch.setattr(discord_parse, "_download_to", boom)

    job = Job(job_id="vf", asset_id="vid", prompt=f"{SHORT} --video", kind="video")
    JOBS[job.job_id] = job
    PENDING_VIDEO.append(job.job_id)

    ingest._ingest_message(_vid_msg(710, _ACK))
    ingest._ingest_message(
        _vid_msg(711, _FINAL, atts=[("https://cdn/final.webp", "v.webp")], buttons=_FINAL_BTNS)
    )
    assert job.status == Status.FAILED
    assert job.error_code == "VIDEO_DOWNLOAD_FAILED"
    tags = _tags()
    assert "VIDEO_FAILED" in tags
    assert "JOB_FAILED" not in tags


# --------------------------- R2: dead-job poisoning ---------------------------


def test_terminal_video_leaves_pending_so_next_binds(tmp_path):
    """A failed video must not poison the next video's bind (review R2): a
    terminal transition removes it from PENDING_VIDEO, so the next ack binds the
    LIVE job, not the dead one."""
    _reset()
    clear()
    config.cfg = _cfg(tmp_path)
    dead = Job(job_id="va", asset_id="a", prompt=f"{SHORT} --video", kind="video")
    JOBS[dead.job_id] = dead
    PENDING_VIDEO.append(dead.job_id)
    dead._fail("VIDEO_RESULT_TIMEOUT", "timed out")  # the reaper path
    assert dead.job_id not in PENDING_VIDEO  # R2: cleaned up at terminal

    live = Job(
        job_id="vb", asset_id="b", prompt="https://s.mj.run/NEW --video --loop", kind="video"
    )
    JOBS[live.job_id] = live
    PENDING_VIDEO.append(live.job_id)
    bound = matching._match_video("Creating video with prompt **<https://s.mj.run/NEW> --video 1**")
    assert bound is live
    assert live.video_match_key == "https://s.mj.run/NEW"


def test_match_video_skips_dead_pending_entry():
    """Defense in depth: even if a terminal/evicted job is still in PENDING_VIDEO,
    the bind path pops past it to the live job. (review R2)"""
    _reset()
    dead = Job(job_id="vd", asset_id="a", prompt="p", kind="video")
    dead.status = Status.FAILED
    live = Job(job_id="vl", asset_id="a", prompt="p", kind="video")
    JOBS["vd"] = dead
    JOBS["vl"] = live
    PENDING_VIDEO.extend(["vd", "vl"])  # dead one first
    bound = matching._match_video(f"Creating video **<{SHORT}> --video 1**")
    assert bound is live
    assert not PENDING_VIDEO  # both popped (dead skipped, live bound)


# --------------------------- R1: serial-submission guard ----------------------


def test_video_route_rejects_second_while_one_unbound(tmp_path):
    """The /video route serializes submission: while a video is awaiting its bind
    (PENDING_VIDEO non-empty) a second submit is refused VIDEO_IN_FLIGHT, so the
    FIFO bind stays unambiguous. (review R1)"""
    _reset()
    config.cfg = _cfg(tmp_path)
    runtime._ready.set()
    try:
        PENDING_VIDEO.append("already-awaiting-bind")
        client = bridge.app.test_client()
        r = client.post(
            "/video", json={"prompt": "https://cdn/x.png --video --loop", "asset_id": "z"}
        )
        assert r.status_code == 409
        assert r.get_json()["code"] == "VIDEO_IN_FLIGHT"
    finally:
        runtime._ready.clear()
        _reset()


# --------------------------- V-3: video result-button derived routing ---------


def test_video_upscale_solo_routes_to_job_derived(monkeypatch, tmp_path):
    """A video_virtual_upscale SOLO (an mp4 replying to the video grid message)
    routes into the job's `derived` list via _video_result_parent + the existing
    _ingest_derived download (format-agnostic — handles mp4). (V-3)"""
    _reset()
    clear()
    config.cfg = _cfg(tmp_path)

    def fake_dl(url, path):
        Path(path).write_bytes(b"\x00\x00\x00\x18ftypmp42" + b"x" * 32)
        return 40

    monkeypatch.setattr(discord_parse, "_download_to", fake_dl)

    job = Job(job_id="vu", asset_id="vid", prompt=f"{SHORT} --video", kind="video")
    job.status = Status.DONE
    job.message_id = 800  # the video grid result message the SOLO replies to
    JOBS[job.job_id] = job

    solo = _vid_msg(
        801,
        f"**<{SHORT}> --end loop --video 1 --aspect 1:1** (fast)",
        atts=[("https://cdn/u_1_720.mp4", "uuid_1_720_N.mp4")],
        buttons=["MJ::JOB::animate_high_extend::1::uuid", "MJ::JOB::animate_low_extend::1::uuid"],
        ref_id=800,  # replies to the grid
    )
    ingest._ingest_message(solo)

    assert len(job.derived) == 1
    d = job.derived[0]
    assert d["path"].endswith(".mp4")
    assert Path(d["path"]).exists()
    # Artifact-aware classification: the SOLO mp4 (content has --video but no
    # --motion) is labeled "animation" by its video content_type, not "variation".
    assert d["action_kind"] == "animation"
    assert "MJ_DERIVED_RECEIVED" in _tags()
    # The SOLO carries animate_*_extend::1 buttons, so it is recorded as an
    # actionable surface keyed by slot 1 — this is what lets mj_action(extend_high|
    # extend_low, slot=1) target it; the extended clip then routes back via
    # _job_by_upscale_message_id. (V-3)
    assert job.upscale_message_ids.get(1) == 801
    # The surface registration is itself a signal (not a silent mutation): the
    # trace carries MJ_ACTION_SURFACE_REGISTERED with the slot, the SOLO message
    # id, and surface_kind=video_solo — so the action chain's middle link is
    # readable from the event stream, not just inferable from bridge state. (V-3)
    surface = next((r for r in snapshot() if r["tag"] == "MJ_ACTION_SURFACE_REGISTERED"), None)
    assert surface is not None
    assert surface["payload"]["slot"] == 1
    assert surface["payload"]["message_id"] == 801
    assert surface["payload"]["surface_kind"] == "video_solo"


def test_video_result_parent_matches_only_done_video_grid():
    """_video_result_parent matches a DONE video job by its result message_id —
    not an image job, and crucially NOT a still-in-progress video (whose own
    final result replies to its message and must complete, not route to derived
    — the regression caught live 2026-06-16)."""
    _reset()
    vid = Job(job_id="vv", asset_id="a", prompt="p", kind="video")
    vid.message_id = 900
    vid.status = Status.DONE
    img = Job(job_id="ii", asset_id="a", prompt="p")  # kind defaults to "image"
    img.message_id = 901
    img.status = Status.DONE
    inprog = Job(job_id="vp", asset_id="a", prompt="p", kind="video")
    inprog.message_id = 902
    inprog.status = Status.PROGRESS
    for j in (vid, img, inprog):
        JOBS[j.job_id] = j
    assert matching._video_result_parent(900) is vid  # DONE video → derived parent
    assert matching._video_result_parent(901) is None  # image grid never matches here
    assert matching._video_result_parent(902) is None  # in-progress video → its result completes


def test_video_upscale_slot_selects_the_right_button():
    """video_upscale folds the slot into the button match — all four
    video_virtual_upscale buttons share ONE (grid) message, so the slot lives in
    the custom_id, not in a separate per-slot message. (V-3)"""
    cids = [f"MJ::JOB::video_virtual_upscale::{n}::uuid" for n in (1, 2, 3, 4)]
    cids.append("MJ::JOB::reroll::0::uuid::SOLO")
    msg = _vid_msg(950, "grid", buttons=cids)
    for n in (1, 2, 3, 4):
        assert (
            discord_parse._find_action_custom_id(msg, "video_upscale", slot=n)
            == f"MJ::JOB::video_virtual_upscale::{n}::uuid"
        )
    # video_upscale with no slot defaults to ::1.
    assert (
        discord_parse._find_action_custom_id(msg, "video_upscale")
        == "MJ::JOB::video_virtual_upscale::1::uuid"
    )
    # The grid's reroll button is present but video_reroll is NOT an exposed
    # action (deferred, review #9 F2: untracked result + bind-perturbation), so
    # it has no marker and never matches — even though the button is right there.
    assert discord_parse._find_action_custom_id(msg, "video_reroll") is None

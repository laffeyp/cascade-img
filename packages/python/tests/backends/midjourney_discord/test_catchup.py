"""Behavior contract for the catch-up surface: the channel buffer,
GET /channel/recent, and POST /adopt/<message_id>.

No live Discord: the buffer is fed fake messages; the routes run through
Flask's test client with the Discord seams (``_run_on_loop``,
``discord_parse._download_to``) monkeypatched, mirroring the action-route
suite's approach.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from cascade_img.backends.midjourney_discord.config import MJ_BOT_ID
from cascade_img.backends.midjourney_discord.http import catchup
from cascade_img.backends.midjourney_discord.http.app import app
from cascade_img.backends.midjourney_discord.jobs import job_table
from cascade_img.backends.midjourney_discord.jobs.job import Job, Status
from cascade_img.backends.midjourney_discord.jobs.job_table import JOBS, LOCK
from cascade_img.backends.midjourney_discord.transport import channel_buffer, discord_parse, runtime
from cascade_img.backends.midjourney_discord.transport.channel_buffer import (
    _classify_kind,
    message_record,
    recent_records,
    record_message,
)
from cascade_img.vocabulary import snapshot


def _reset():
    with LOCK:
        JOBS.clear()
        job_table.PENDING_GRID.clear()
        job_table.PENDING_VIDEO.clear()
    with channel_buffer._BUFFER_LOCK:
        channel_buffer.CHANNEL_BUFFER.clear()


@pytest.fixture(autouse=True)
def _clean_state():
    _reset()
    yield
    _reset()


# ---- fakes ------------------------------------------------------------------


class _Btn:
    def __init__(self, custom_id):
        self.custom_id = custom_id


class _Row:
    def __init__(self, children):
        self.children = children


class _Att:
    def __init__(self, filename="img.png", content_type="image/png", w=3104, h=1552):
        self.filename = filename
        self.url = f"https://cdn.example/{filename}"
        self.content_type = content_type
        self.width = w
        self.height = h


def _msg(
    mid=111,
    content="**a prompt --ar 2:1 --no x, cscidnocollideaabbccdd** - Image #4",
    attachments=None,
    components=None,
    author_id=MJ_BOT_ID,
):
    return SimpleNamespace(
        id=mid,
        content=content,
        attachments=attachments if attachments is not None else [_Att()],
        components=components or [],
        author=SimpleNamespace(id=author_id),
        created_at=None,
        reference=None,
    )


def _solo_components(uuid="cafef00d"):
    return [
        _Row(
            [
                _Btn(f"MJ::JOB::low_variation::1::{uuid}::SOLO"),
                _Btn(f"MJ::JOB::high_variation::1::{uuid}::SOLO"),
                _Btn(f"MJ::JOB::pan_left::1::{uuid}::SOLO"),
            ]
        )
    ]


# ---- classification + record extraction --------------------------------------


def test_classify_kind_covers_the_four_kinds():
    att = {"content_type": "image/png", "filename": "x.png"}
    assert _classify_kind("prompt text - Image #2", [att]) == "solo"
    assert _classify_kind("prompt text", [att]) == "grid"
    assert _classify_kind("url --video 1 --motion high", [att]) == "video"
    vid = {"content_type": "video/mp4", "filename": "clip.mp4"}
    assert _classify_kind("no flags at all", [vid]) == "video"
    assert _classify_kind("moderation notice", []) == "other"


def test_message_record_extracts_token_slot_and_buttons():
    m = _msg(components=_solo_components())
    rec = message_record(m)
    assert rec["message_id"] == "111"
    assert rec["kind"] == "solo"
    assert rec["routing_token"] == "aabbccdd"
    assert rec["slot_label"] == "Image #4"
    assert rec["attachment"]["width"] == 3104
    assert set(rec["buttons"]) >= {"vary_subtle", "vary_strong", "pan_left"}
    assert "zoom_out_2x" not in rec["buttons"]


def test_record_message_replaces_same_id_and_bounds():
    record_message(_msg(mid=1, content="first"))
    record_message(_msg(mid=1, content="first (edited) cscidnocollide11112222"))
    assert len(recent_records(10)) == 1
    assert recent_records(10)[0]["routing_token"] == "11112222"
    for i in range(2, channel_buffer._BUFFER_MAXLEN + 10):
        record_message(_msg(mid=i))
    assert len(channel_buffer.CHANNEL_BUFFER) == channel_buffer._BUFFER_MAXLEN


# ---- GET /channel/recent ------------------------------------------------------


def test_channel_recent_resolves_tracked_vs_untracked():
    record_message(_msg(mid=500, content="tracked grid cscidnocollide99998888"))
    record_message(_msg(mid=501, content="a manual press - Image #4"))
    job = Job(job_id="j1", asset_id="a", prompt="p", status=Status.DONE)
    job.message_id = 500
    with LOCK:
        JOBS[job.job_id] = job

    with app.test_client() as client:
        r = client.get("/channel/recent?n=10")
    assert r.status_code == 200
    body = r.get_json()
    assert body["ok"] is True
    by_id = {m["message_id"]: m for m in body["result"]["messages"]}
    assert by_id["500"]["tracked_job_id"] == "j1"
    assert by_id["501"]["tracked_job_id"] is None
    assert body["result"]["source"] == "buffer"
    tags = [r["tag"] for r in snapshot()]
    assert "CHANNEL_CATCHUP_READ" in tags


def test_channel_recent_rejects_bad_n():
    with app.test_client() as client:
        r = client.get("/channel/recent?n=notanumber")
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "INVALID_N"


def test_channel_recent_cold_buffer_not_ready_is_503():
    runtime._ready.clear()
    with app.test_client() as client:
        r = client.get("/channel/recent?n=5")
    assert r.status_code == 503
    assert r.get_json()["error"]["code"] == "DISCORD_NOT_READY"


# ---- POST /adopt/<message_id> ---------------------------------------------------


def test_adopt_requires_asset_id():
    with app.test_client() as client:
        r = client.post("/adopt/123", json={})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "MISSING_ASSET_ID"


def test_adopt_already_tracked_returns_409_with_job_id():
    job = Job(job_id="j2", asset_id="a", prompt="p", status=Status.DONE)
    job.upscale_message_id = 777
    with LOCK:
        JOBS[job.job_id] = job
    with app.test_client() as client:
        r = client.post("/adopt/777", json={"asset_id": "again"})
    assert r.status_code == 409
    err = r.get_json()["error"]
    assert err["code"] == "ALREADY_TRACKED"
    assert err["job_id"] == "j2"


def test_adopt_solo_happy_path_registers_action_surface(monkeypatch, tmp_path):
    runtime._ready.set()
    solo = _msg(mid=888, components=_solo_components())

    monkeypatch.setattr(catchup, "_run_on_loop", lambda coro, timeout: _close(coro) or solo)
    monkeypatch.setattr(
        discord_parse, "_download_to", lambda url, path: path.write_bytes(b"x") or 1
    )
    monkeypatch.setattr(
        catchup,
        "_cfg",
        lambda: SimpleNamespace(output_dir=tmp_path, channel_id=1, guild_id=None),
    )

    with app.test_client() as client:
        r = client.post("/adopt/888", json={"asset_id": "manual-u4"})
    assert r.status_code == 200, r.get_json()
    result = r.get_json()["result"]
    assert result["kind"] == "solo"
    assert result["origin"] == "adopted"
    assert "vary_strong" in result["buttons"]

    with LOCK:
        job = JOBS[result["job_id"]]
    assert job.origin == "adopted"
    assert job.status == Status.DONE
    # The adopted SOLO is the action surface: mj_action's non-video path reads
    # upscale_message_id, and derived replies route by the same id.
    assert job.upscale_message_id == 888
    assert job.upscale_message_ids[4] == 888
    tags = [rec["tag"] for rec in snapshot()]
    assert "MESSAGE_ADOPTED" in tags

    # Idempotent: adopting the same message again is ALREADY_TRACKED.
    with app.test_client() as client:
        r2 = client.post("/adopt/888", json={"asset_id": "again"})
    assert r2.status_code == 409
    assert r2.get_json()["error"]["job_id"] == job.job_id


def test_adopt_rejects_non_mj_author_and_no_artifact(monkeypatch, tmp_path):
    runtime._ready.set()
    monkeypatch.setattr(
        catchup,
        "_cfg",
        lambda: SimpleNamespace(output_dir=tmp_path, channel_id=1, guild_id=None),
    )

    foreign = _msg(mid=901, author_id=42)
    monkeypatch.setattr(catchup, "_run_on_loop", lambda coro, timeout: _close(coro) or foreign)
    with app.test_client() as client:
        r = client.post("/adopt/901", json={"asset_id": "x"})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "NOT_AN_MJ_MESSAGE"

    bare = _msg(mid=902, attachments=[])
    monkeypatch.setattr(catchup, "_run_on_loop", lambda coro, timeout: _close(coro) or bare)
    with app.test_client() as client:
        r = client.post("/adopt/902", json={"asset_id": "x"})
    assert r.status_code == 400
    assert r.get_json()["error"]["code"] == "NOT_AN_MJ_MESSAGE"


def test_adopt_video_message_becomes_video_surface(monkeypatch, tmp_path):
    runtime._ready.set()
    vid = _msg(
        mid=903,
        content="<https://s.mj.run/abc> --video 1 --motion high",
        attachments=[_Att(filename="clip.webp", content_type="image/webp")],
        components=[_Row([_Btn("MJ::JOB::video_virtual_upscale::1::u::SOLO")])],
    )
    monkeypatch.setattr(catchup, "_run_on_loop", lambda coro, timeout: _close(coro) or vid)
    monkeypatch.setattr(
        discord_parse, "_download_to", lambda url, path: path.write_bytes(b"x") or 1
    )
    monkeypatch.setattr(
        catchup,
        "_cfg",
        lambda: SimpleNamespace(output_dir=tmp_path, channel_id=1, guild_id=None),
    )
    with app.test_client() as client:
        r = client.post("/adopt/903", json={"asset_id": "manual-video"})
    assert r.status_code == 200
    result = r.get_json()["result"]
    assert result["kind"] == "video"
    with LOCK:
        job = JOBS[result["job_id"]]
    # video actions (video_upscale) target message_id on a DONE video job.
    assert job.kind == "video"
    assert job.message_id == 903
    assert job.status == Status.DONE


def _close(coro):
    """Close an unawaited coroutine so the fake _run_on_loop doesn't warn."""
    if hasattr(coro, "close"):
        coro.close()
    return None

"""Behavior contract for the persistent JobStore + the bridge's rehydration.

The store is the durability sidecar: a restart must resume tracking
in-flight jobs instead of dropping them. These tests pin (a) the store's
put/load/delete + terminal filtering, (b) the str-enum serialization trap, and
(c) the bridge reconstructing typed Job objects + PENDING_GRID on rehydrate.
"""

from __future__ import annotations

from collections import OrderedDict

from cascade_img.backends.midjourney_discord.job_store import JobStore


def _row(job_id: str, status, **extra) -> dict:
    """A full asdict(Job)-shaped row with overridable fields."""
    base = {
        "job_id": job_id,
        "asset_id": "a",
        "prompt": "p",
        "request_token": "tok",
        "upscale": None,
        "status": status,
        "progress": "",
        "message_id": None,
        "mj_job_uuid": None,
        "image_path": None,
        "image_url": None,
        "grid_path": None,
        "grid_url": None,
        "upscale_paths": {},
        "upscale_pending": [],
        "upscale_press_failures": {},
        "error": None,
        "error_code": None,
        "created_at": 1.0,
        "updated_at": 2.0,
        "match_path": None,
    }
    base.update(extra)
    return base


def test_load_nonterminal_excludes_terminal():
    store = JobStore(":memory:")
    store.put(_row("j1", "progress"))
    store.put(_row("j2", "submitted"))
    store.put(_row("j3", "done"))
    store.put(_row("j4", "failed"))
    assert {r["job_id"] for r in store.load_nonterminal()} == {"j1", "j2"}
    store.close()


def test_put_upserts_on_same_job_id():
    store = JobStore(":memory:")
    store.put(_row("j1", "queued", progress=""))
    store.put(_row("j1", "progress", progress="50%"))
    rows = store.load_nonterminal()
    assert len(rows) == 1
    assert rows[0]["status"] == "progress"
    assert rows[0]["progress"] == "50%"
    store.close()


def test_delete_removes_row():
    store = JobStore(":memory:")
    store.put(_row("j1", "progress"))
    assert store.count() == 1
    store.delete("j1")
    assert store.count() == 0
    assert store.load_nonterminal() == []
    store.close()


def test_status_enum_member_persists_as_value():
    """A Status(str, Enum) member must store as 'done', not 'Status.DONE', or
    the terminal filter silently rehydrates finished jobs."""
    from cascade_img.backends.midjourney_discord.bridge import Status

    store = JobStore(":memory:")
    store.put(_row("term", Status.DONE))
    store.put(_row("live", Status.PROGRESS))
    assert {r["job_id"] for r in store.load_nonterminal()} == {"live"}
    store.close()


def test_roundtrip_through_disk_preserves_data(tmp_path):
    db = tmp_path / "jobs.db"
    s1 = JobStore(db)
    s1.put(
        _row(
            "j1",
            "upscaling",
            upscale="all",
            upscale_pending=[2, 4],
            upscale_paths={1: "/p/u1.png"},
            message_id=123,
        )
    )
    s1.close()
    rows = JobStore(db).load_nonterminal()
    assert len(rows) == 1
    r = rows[0]
    assert r["upscale"] == "all"
    assert r["upscale_pending"] == [2, 4]
    assert r["message_id"] == 123
    # JSON stringifies dict keys at the store layer; the bridge coerces back.
    assert r["upscale_paths"] == {"1": "/p/u1.png"}


def test_bridge_rehydrates_nonterminal_jobs(monkeypatch, tmp_path):
    """The bridge restores non-terminal jobs as typed Job objects and coerces the
    JSON-lossy fields. In-flight jobs (PROGRESS/UPSCALING, grid already seen)
    resume intact; pre-grid jobs (QUEUED/SUBMITTED/...) are failed with
    RESUBMIT_REQUIRED so they cannot linger as never-evicted phantoms."""
    from cascade_img.backends.midjourney_discord import bridge
    from cascade_img.backends.midjourney_discord.bridge import Status

    store = JobStore(tmp_path / "jobs.db")
    store.put(_row("live1", "submitted"))
    store.put(
        _row(
            "live2",
            "upscaling",
            upscale="all",
            upscale_pending=[2, 4],
            upscale_paths={1: "/p/u1.png"},
        )
    )
    store.put(_row("dead", "done"))

    monkeypatch.setattr(bridge, "_store", store)
    monkeypatch.setattr(bridge, "JOBS", OrderedDict())
    monkeypatch.setattr(bridge, "PENDING_GRID", [])

    n = bridge._rehydrate_jobs()
    assert n == 2  # terminal excluded; both non-terminal rows restored into JOBS
    assert set(bridge.JOBS) == {"live1", "live2"}

    j2 = bridge.JOBS["live2"]
    assert j2.status == Status.UPSCALING  # coerced back to the enum, resumed
    assert j2.upscale_pending == [2, 4]
    assert j2.upscale_paths == {1: "/p/u1.png"}  # int key restored

    # The pre-grid job is failed (terminal, hence TTL-evictable) rather than
    # rejoining PENDING_GRID as a potential phantom; the in-flight one is not.
    j1 = bridge.JOBS["live1"]
    assert j1.status == Status.FAILED
    assert j1.error_code == "RESUBMIT_REQUIRED"
    assert "live1" not in bridge.PENDING_GRID
    assert "live2" not in bridge.PENDING_GRID
    store.close()

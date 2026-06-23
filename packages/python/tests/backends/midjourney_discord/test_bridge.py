"""Behavior contract for the concurrency + matching work:
JOBS LRU+TTL eviction, /wait Condition-based callback, token-based grid
matching, BRIDGE_SHUTDOWN signal, port range validation.

These tests exercise the daemon's internals directly (no live Discord, no
running Flask). The matching tests prove the collision-resistant routing
without firing a real /imagine.
"""

from __future__ import annotations

import threading
import time

from cascade_img.backends.midjourney_discord import bridge, config, job_table
from cascade_img.backends.midjourney_discord.bridge import _emit_shutdown
from cascade_img.backends.midjourney_discord.job import Job, Status, _evict_if_needed
from cascade_img.backends.midjourney_discord.job_table import JOBS, LOCK, TERMINAL_CV
from cascade_img.backends.midjourney_discord.matching import _match_grid, _token_needle
from cascade_img.vocabulary import clear, snapshot


def _reset_jobs():
    with LOCK:
        JOBS.clear()
        job_table.PENDING_GRID.clear()
        bridge._shutdown_emitted = False


# ---------------- token-based grid matching ----------------


def test_token_needle_format():
    assert _token_needle("abc12345") == "cscidnocollideabc12345"


def test_match_grid_routes_by_token_not_substring():
    """Two prompts sharing a prefix must NOT cross-match. The per-job
    request_token disambiguates."""
    _reset_jobs()
    job_a = Job(
        job_id="a",
        asset_id="mountain-icon",
        prompt="a mountain icon at dawn",
        request_token="aaa11111",
    )
    job_b = Job(
        job_id="b",
        asset_id="river-scene",
        prompt="a mountain icon at dawn over water",
        request_token="bbb22222",
    )
    with LOCK:
        JOBS["a"] = job_a
        JOBS["b"] = job_b
        job_table.PENDING_GRID.append("a")
        job_table.PENDING_GRID.append("b")

    # MJ message for job B — contains the prompt AND token B
    msg_for_b = "a mountain icon at dawn over water --no cscidnocollidebbb22222 (Waiting to start)"
    matched = _match_grid(msg_for_b)
    assert matched is not None
    assert matched.job_id == "b"

    msg_for_a = "a mountain icon at dawn --no cscidnocollideaaa11111 (Waiting to start)"
    matched = _match_grid(msg_for_a)
    assert matched is not None
    assert matched.job_id == "a"


def test_match_grid_progress_fallback_uses_token():
    """V7 grid-as-new-message path also routes by token."""
    _reset_jobs()
    job = Job(job_id="x", asset_id="x", prompt="anything", request_token="ccc33333")
    job.status = Status.PROGRESS
    with LOCK:
        JOBS["x"] = job
        # NOT in PENDING_GRID — already moved out.

    matched = _match_grid("here is your grid --no cscidnocollideccc33333")
    assert matched is not None
    assert matched.job_id == "x"
    assert matched.match_path == "progress_fallback"


def test_tagged_prompt_appends_token():
    j = Job(job_id="x", asset_id="x", prompt="hi --ar 1:1", request_token="ttttoken")
    assert j.tagged_prompt() == "hi --ar 1:1 --no cscidnocollidettttoken"


# ---------------- JOBS LRU+TTL eviction ----------------


def test_evict_ttl_drops_old_terminal_jobs(monkeypatch):
    _reset_jobs()
    clear()
    now = time.time()
    # Three terminal jobs older than the TTL.
    monkeypatch.setattr(config, "TERMINAL_AGE_SECONDS", 10.0)
    for i in range(3):
        j = Job(job_id=f"old{i}", asset_id=f"a{i}", prompt="p")
        j.status = Status.DONE
        j.created_at = now - 1000
        j.updated_at = now - 100
        JOBS[j.job_id] = j
    # One fresh terminal job (under TTL).
    fresh = Job(job_id="fresh", asset_id="fresh", prompt="p")
    fresh.status = Status.DONE
    fresh.updated_at = now - 1
    JOBS["fresh"] = fresh

    _evict_if_needed()

    remaining = list(JOBS.keys())
    assert "fresh" in remaining
    assert "old0" not in remaining
    assert "old1" not in remaining
    assert "old2" not in remaining
    # Three JOB_EVICTED signals with reason=terminal_age_ttl.
    evicted = [r for r in snapshot() if r["tag"] == "JOB_EVICTED"]
    assert len(evicted) == 3
    assert all(r["payload"]["reason"] == "terminal_age_ttl" for r in evicted)


def test_evict_lru_caps_size(monkeypatch):
    _reset_jobs()
    clear()
    monkeypatch.setattr(config, "MAX_JOBS", 3)
    monkeypatch.setattr(config, "TERMINAL_AGE_SECONDS", 9999.0)
    # Fill past cap; first three are DONE so LRU can evict them.
    for i in range(5):
        j = Job(job_id=f"j{i}", asset_id=f"a{i}", prompt="p")
        j.status = Status.DONE if i < 3 else Status.PROGRESS
        JOBS[j.job_id] = j
    _evict_if_needed()
    # Cap=3; we had 5; we expect 2 evictions of the oldest terminal jobs.
    assert len(JOBS) == 3
    # In-flight jobs preserved.
    assert "j3" in JOBS and "j4" in JOBS
    evicted = [r for r in snapshot() if r["tag"] == "JOB_EVICTED"]
    assert len(evicted) == 2
    assert all(r["payload"]["reason"] == "lru_capacity" for r in evicted)


def test_evict_preserves_in_flight_when_capacity_exhausted(monkeypatch):
    """If everything over-cap is in-flight, eviction stops and the dict
    grows past cap rather than orphaning a live job."""
    _reset_jobs()
    monkeypatch.setattr(config, "MAX_JOBS", 2)
    for i in range(5):
        j = Job(job_id=f"f{i}", asset_id=f"a{i}", prompt="p")
        j.status = Status.PROGRESS
        JOBS[j.job_id] = j
    _evict_if_needed()
    assert len(JOBS) == 5  # all preserved


# ---------------- /wait Condition-based callback ----------------


def test_terminal_cv_wakes_waiter_on_complete():
    """A thread waiting on TERMINAL_CV wakes when a job hits DONE — proves
    /wait will be unblocked the moment the daemon emits JOB_COMPLETED."""
    _reset_jobs()
    j = Job(job_id="w1", asset_id="w1", prompt="p")
    j.status = Status.PROGRESS
    JOBS["w1"] = j

    woke = threading.Event()

    def waiter():
        with TERMINAL_CV:
            while j.status not in (Status.DONE, Status.FAILED):
                TERMINAL_CV.wait(timeout=3.0)
        woke.set()

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.05)
    # Trigger _complete from another thread; this notifies TERMINAL_CV.
    j._complete()
    t.join(timeout=2.0)
    assert woke.is_set()


def test_terminal_cv_wakes_waiter_on_fail():
    _reset_jobs()
    j = Job(job_id="w2", asset_id="w2", prompt="p")
    j.status = Status.PROGRESS
    JOBS["w2"] = j

    woke = threading.Event()

    def waiter():
        with TERMINAL_CV:
            while j.status not in (Status.DONE, Status.FAILED):
                TERMINAL_CV.wait(timeout=3.0)
        woke.set()

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.05)
    j._fail("SUBMIT_FAILED", "synthetic failure for test")
    t.join(timeout=2.0)
    assert woke.is_set()


# ---------------- BRIDGE_SHUTDOWN ----------------


def test_bridge_shutdown_emits_once():
    _reset_jobs()
    clear()
    _emit_shutdown("test_first")
    _emit_shutdown("test_second")  # idempotent
    tags = [r for r in snapshot() if r["tag"] == "BRIDGE_SHUTDOWN"]
    assert len(tags) == 1
    assert tags[0]["payload"]["reason"] == "test_first"

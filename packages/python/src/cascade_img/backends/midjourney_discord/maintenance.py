"""Stalled-job reaper: the periodic sweep that fails silent in-flight jobs.

Extracted from bridge.py (sprint 023.5).

Binding discipline: the timeout is read as ``config.INFLIGHT_TIMEOUT_SECONDS``
(a module attribute) so tests that retune it patch ``config.INFLIGHT_TIMEOUT_SECONDS``
and the reaper sees the new value; the shutdown gate is read as
``runtime._shutdown_event`` for the same reason (it is an Event, never rebound,
so by-name would also be safe, but the module-attribute read keeps the rule
uniform).
"""

from __future__ import annotations

import logging
import time

from cascade_img.backends.midjourney_discord import config, runtime
from cascade_img.backends.midjourney_discord.job import Status
from cascade_img.backends.midjourney_discord.job_table import (
    JOBS,
    LOCK,
    PENDING_GRID,
    TERMINAL_CV,
)

log = logging.getLogger("cascade_img.bridge.maintenance")


# Non-terminal statuses: a job in any of these is still in flight and not yet
# evictable (eviction only drops DONE/FAILED). The reaper watches them for
# stalls; everything not listed here is terminal.
_NON_TERMINAL_STATUSES = (
    Status.QUEUED,
    Status.SUBMITTED,
    Status.SUBMITTED_UNCONFIRMED,
    Status.PROGRESS,
    Status.UPSCALING,
)


def _reap_stalled_jobs() -> int:
    """Fail in-flight jobs that have gone silent past INFLIGHT_TIMEOUT_SECONDS.

    A non-terminal job whose ``updated_at`` hasn't advanced within the timeout is
    a stall: MJ stopped editing the progress message, a rehydrated UPSCALING
    job's upscales never landed (its presses fired pre-restart and can't be
    safely re-fired), or a SUBMITTED_UNCONFIRMED job MJ never processed. Left
    alone it sits non-terminal forever — eviction only drops DONE/FAILED, so it
    is never TTL/LRU-reaped and remains a permanent phantom row against
    MAX_JOBS. Failing it RESUBMIT_REQUIRED makes it terminal (hence evictable)
    and tells the operator to re-submit and verify rather than the daemon risking
    a double-bill by silently re-firing. Returns the count reaped.

    Race-safe: each candidate is re-checked under TERMINAL_CV (an RLock-backed
    condition, so ``_fail`` re-enters cleanly) so a job that completed between the
    scan and the fail is left alone.
    """
    now = time.time()
    reaped = 0
    with LOCK:
        candidates = [
            j
            for j in JOBS.values()
            if j.status in _NON_TERMINAL_STATUSES
            and (now - j.updated_at) > config.INFLIGHT_TIMEOUT_SECONDS
        ]
    for job in candidates:
        with TERMINAL_CV:
            if job.status not in _NON_TERMINAL_STATUSES:
                continue  # raced to terminal between the scan and now
            prior = job.status
            age = int(now - job.updated_at)
            job._fail(
                "RESUBMIT_REQUIRED",
                f"in-flight job stalled — no progress for {age}s (was {prior}); "
                "Midjourney outcome unconfirmable, re-submit and verify.",
            )
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        log.warning(
            f"[{job.asset_id}] reaped stalled job {job.job_id} "
            f"RESUBMIT_REQUIRED after {age}s of no progress"
        )
        reaped += 1
    return reaped


def _reaper_loop(interval: float) -> None:
    """Periodic stalled-job sweep until shutdown. Sleeps on ``_shutdown_event``
    so a SIGINT/SIGTERM cuts the wait short."""
    while not runtime._shutdown_event.wait(timeout=interval):
        try:
            _reap_stalled_jobs()
        except Exception as e:  # a sweep failure must never kill the reaper
            log.warning(f"reaper sweep failed: {type(e).__name__}: {e}")

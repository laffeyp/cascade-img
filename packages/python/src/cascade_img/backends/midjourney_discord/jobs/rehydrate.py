"""Startup rehydration: reconstruct non-terminal jobs from the durable store.

Sits above ``job`` / ``job_table`` / ``persistence``: it is the place that
*constructs* ``Job`` from stored rows and inserts them into the table.

Binding discipline: the durable store is read as ``persistence._store`` (a module
attribute reassigned in ``main()``), never imported by value.
"""

from __future__ import annotations

import logging

from cascade_img.backends.midjourney_discord.jobs import job_table, persistence
from cascade_img.backends.midjourney_discord.jobs.job import Job, Status
from cascade_img.backends.midjourney_discord.jobs.job_table import LOCK

log = logging.getLogger("cascade_img.bridge.rehydrate")


def _job_from_row(row: dict) -> Job:
    """Reconstruct a Job from a stored row, coercing the JSON-lossy fields:
    ``status`` back to the Status enum, and the int-keyed dicts (JSON
    stringifies dict keys) back to int keys."""
    row = dict(row)
    row["status"] = Status(row["status"])
    # Drop reservation sentinels ("" placeholders set under LOCK before a
    # download) symmetrically with _persist: a rehydrated "" would look like a
    # claimed-but-empty slot the matchers never re-claim. Stripping restores the
    # slot to a re-matchable state so the restart re-downloads.
    if row.get("grid_path") == "":
        row["grid_path"] = None
    row["upscale_paths"] = {
        int(k): v for k, v in (row.get("upscale_paths") or {}).items() if v != ""
    }
    row["upscale_message_ids"] = {
        int(k): int(v) for k, v in (row.get("upscale_message_ids") or {}).items()
    }
    row["upscale_pending"] = [int(x) for x in (row.get("upscale_pending") or [])]
    row["upscale_press_failures"] = {
        int(k): v for k, v in (row.get("upscale_press_failures") or {}).items()
    }
    row["upscale_download_failures"] = {
        int(k): v for k, v in (row.get("upscale_download_failures") or {}).items()
    }
    # Drop any derived entry still on its reservation sentinel (path==""): if a
    # concurrent touch() snapshotted the job mid-download, the store can hold a
    # claimed-but-undownloaded entry whose result never lands after a restart.
    row["derived"] = [d for d in (row.get("derived") or []) if d.get("path")]
    return Job(**row)


def _rehydrate_jobs() -> int:
    """Restore non-terminal jobs from the store into JOBS at startup. Returns
    the count restored.

    PROGRESS jobs have a grid genuinely in flight that the grid matcher can still
    claim if MJ posts it after the restart, so they resume. UPSCALING jobs are
    subtler: their U-button presses already fired before the restart and cannot
    be safely re-fired (a second press double-bills), so they resume ONLY if MJ
    posts the SOLO upscale messages after the daemon is back up — the upscale
    matcher claims those. An UPSCALING (or PROGRESS) job whose result never
    arrives would otherwise sit non-terminal forever; the inflight reaper
    (:func:`_reap_stalled_jobs`) catches that stall and fails it
    RESUBMIT_REQUIRED, the same terminal the pre-grid case below uses.

    Pre-grid jobs (QUEUED / SUBMITTED / SUBMITTED_UNCONFIRMED) are NOT trusted:
    across a daemon restart it is unknowable whether Midjourney processed the
    /imagine, and a pre-grid job that no grid ever matches would sit non-terminal
    forever — never TTL-evicted, a permanent phantom row. They are failed with
    RESUBMIT_REQUIRED so they become terminal (hence evictable) and the operator
    is told to re-submit and verify rather than the daemon silently re-firing
    (which would double-bill if the original did process)."""
    if persistence._store is None:
        return 0
    count = 0
    with LOCK:
        for row in persistence._store.load_nonterminal():
            try:
                job = _job_from_row(row)
            except Exception as e:
                log.warning(f"skipping unrehydratable job row: {e}")
                continue
            job_table.JOBS[job.job_id] = job
            count += 1
            if job.status in (Status.QUEUED, Status.SUBMITTED, Status.SUBMITTED_UNCONFIRMED):
                job._fail(
                    "RESUBMIT_REQUIRED",
                    "pre-grid job could not be resumed across a daemon restart "
                    "(Midjourney processing unconfirmable); re-submit and verify.",
                )
                log.warning(f"[{job.asset_id}] rehydrated pre-grid job failed RESUBMIT_REQUIRED")
    return count

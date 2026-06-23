"""Durable job-store write-through and safe output paths.

Sits below ``job.py`` in the import graph: it references ``Job`` only under
``TYPE_CHECKING`` (``asdict``
works on any dataclass at runtime), so ``Job.touch()`` can import ``_persist``
downward without a cycle.

Binding discipline: ``_store`` is reassigned at startup. Set it via attribute
assignment on this module — ``persistence._store = JobStore(...)`` — and read it
as ``persistence._store``; never ``from .persistence import _store`` (that would
bind the ``None`` placeholder).
"""

from __future__ import annotations

import logging
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

from cascade_img.backends.midjourney_discord.jobs.job_store import JobStore
from cascade_img.vocabulary import emit

if TYPE_CHECKING:
    from cascade_img.backends.midjourney_discord.jobs.job import Job

log = logging.getLogger("cascade_img.bridge.persistence")

# Durable job store. None until main() opens it. The in-memory JOBS
# map stays authoritative; this is a write-through mirror for restart recovery.
_store: JobStore | None = None


def _persist(job: Job) -> None:
    """Write-through the job's current state to the durable store. Best-effort:
    JOBS is authoritative, so a persistence failure is logged, not raised. No-op
    when no store is configured (unit tests, in-process embedders)."""
    if _store is None:
        return
    try:
        row = asdict(job)
        # Never persist a derived entry still on its reservation sentinel
        # (path==""): if a concurrent touch() snapshots the job mid-download, a
        # restart's _job_from_row would drop the claimed-but-undownloaded entry
        # and orphan the file. Only complete (path-bearing) derived rows persist.
        row["derived"] = [d for d in row.get("derived") or [] if d.get("path")]
        # Same reservation-sentinel hazard for the grid and per-slot upscale
        # paths: _ingest sets ``grid_path=""`` / ``upscale_paths[idx]=""`` under
        # LOCK before the download, and a concurrent touch() can snapshot the job
        # mid-download. A persisted "" rehydrates as a claimed-but-empty slot the
        # matchers treat as already-downloaded (``grid_path is not None`` /
        # ``idx in upscale_paths``) and never re-claim — a permanent non-terminal
        # phantom. Strip them so a restart re-matches and re-downloads, exactly
        # as the derived path above already does.
        if row.get("grid_path") == "":
            row["grid_path"] = None
        row["upscale_paths"] = {
            k: v for k, v in (row.get("upscale_paths") or {}).items() if v != ""
        }
        _store.put(row)
    except Exception as e:  # durability is best-effort; never break the live path
        log.warning(f"job-store persist failed for {job.job_id}: {e}")


def _unpersist(job_id: str) -> None:
    if _store is None:
        return
    try:
        _store.delete(job_id)
    except Exception as e:
        log.warning(f"job-store delete failed for {job_id}: {e}")


def _safe_output_path(
    *,
    output_dir: Path,
    asset_id: str,
    suffix: str,
    ext: str,
    request_token: str,
    kind: str,
    job_id: str,
) -> Path:
    """Return an output path for the asset, disambiguating on collision.

    If ``<output_dir>/<asset_id><suffix><ext>`` already exists on disk, the
    request_token is woven into the filename to avoid clobbering a concurrent
    job's artifact. The collision is announced via ``OUTPUT_PATH_COLLISION``.
    The asset_id contract is preserved either way: the artifact lands; the
    operator learns from the signal that two jobs shared an asset_id.
    """
    intended = output_dir / f"{asset_id}{suffix}{ext}"
    if not intended.exists():
        return intended
    actual = output_dir / f"{asset_id}_{request_token}{suffix}{ext}"
    emit(
        "OUTPUT_PATH_COLLISION",
        asset_id=asset_id,
        job_id=job_id,
        intended_path=str(intended),
        actual_path=str(actual),
        kind=kind,
    )
    return actual

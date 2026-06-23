"""Shared in-flight job state: the table, its lock, and the pending queues.

Extracted from bridge.py (sprint 023.3). This module is the single owner of the
process-wide job table and its synchronization primitives. Every module that
touches job state imports these objects from here, so there is exactly one
``LOCK`` / ``TERMINAL_CV`` / ``JOBS`` in the process — the locking semantics are
preserved by construction (the objects are imported, never reconstructed).

``Job`` is referenced only under ``TYPE_CHECKING`` (the table is typed but never
constructs a ``Job`` here), so this module sits *below* ``job.py`` and ``job.py``
imports it downward — no cycle.

These containers are mutated in place (``JOBS[id] = ...`` / ``.append`` /
``.pop`` / ``.clear``) and never rebound, so importing them by name elsewhere is
safe. Tests that rebind them (``monkeypatch.setattr``) must target the module
that actually reads them.
"""

from __future__ import annotations

import threading
from collections import OrderedDict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cascade_img.backends.midjourney_discord.jobs.job import Job

JOBS: OrderedDict[str, Job] = OrderedDict()
PENDING_GRID: list[str] = []  # FIFO of job_ids awaiting grid message match
# FIFO of video job_ids fired but not yet bound to MJ's echoed short URL. A
# native-video prompt can't carry the `--no` routing token, so the job is bound
# to the `s.mj.run/XXX` URL MJ mints in its first "Creating video…" ack (F34
# bind-on-vendor-echo), then matched on that key for progress + the final webp.
PENDING_VIDEO: list[str] = []
LOCK = threading.RLock()
TERMINAL_CV = threading.Condition(LOCK)

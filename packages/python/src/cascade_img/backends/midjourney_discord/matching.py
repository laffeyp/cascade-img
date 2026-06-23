"""Message-to-job matchers and job-table lookups.

Extracted from bridge.py (sprint 023.6). These read the shared job table and
route an incoming MJ message to the job it belongs to (grid / video / upscale),
or look a job up by one of its message ids. Pure with respect to Discord — they
take already-extracted ``content`` / ``message_id``, never the live client — so
they sit at L4, below ingest and the routes.

``_session_id_or_raise`` is deliberately NOT here: it reads the live Discord
``client``, which lives higher in the graph, so it stays with the client to keep
this module acyclic.
"""

from __future__ import annotations

import re

from cascade_img.backends.midjourney_discord.job import Job, Status
from cascade_img.backends.midjourney_discord.job_table import (
    JOBS,
    LOCK,
    PENDING_GRID,
    PENDING_VIDEO,
)

IMAGE_TAG_RE = re.compile(r"Image #(\d+)")


def _token_needle(token: str) -> str:
    """The substring _match_grid looks for in MJ's echoed content.

    Per-job request tokens are appended to the outbound prompt as
    ``--no cscidnocollide{token}``; MJ's progress and grid messages echo
    the prompt verbatim, so finding ``cscidnocollide{token}`` in the
    content is a collision-free routing key.
    """
    return f"cscidnocollide{token}"


def _match_grid(content: str) -> Job | None:
    """Find the job whose request token appears in ``content``.

    Matches in two passes: pending jobs (first-touch on MJ's initial
    prompt-echo) and progress-stage jobs whose grid hasn't been saved yet
    (covers the case where MJ posts the completed grid as a new message
    rather than editing the original). Returns ``None`` if no job claims
    this message.
    """
    with LOCK:
        for job_id in list(PENDING_GRID):
            job = JOBS.get(job_id)
            if not job:
                continue
            if _token_needle(job.request_token) in content and "Image #" not in content:
                PENDING_GRID.remove(job_id)
                job.match_path = "pending"
                return job
        for job in JOBS.values():
            if job.status != Status.PROGRESS or job.grid_path is not None:
                continue
            if _token_needle(job.request_token) in content and "Image #" not in content:
                job.match_path = "progress_fallback"
                return job
    return None


_VIDEO_SHORT_URL_RE = re.compile(r"<(https?://s\.mj\.run/[^>\s]+)>")


def _match_video(content: str) -> Job | None:
    """Route a native-video message to its job (F34 bind-on-vendor-echo).

    Video prompts can't carry the ``--no`` request token, so a video job has no
    token to echo. Instead MJ mints a ``s.mj.run/XXX`` short URL for the prompt
    and echoes it in every video message (the "Creating video…" ack, each
    progress edit, and the final). First match an already-bound job whose key is
    in ``content`` (progress + final); otherwise, on MJ's first video echo (it
    carries ``--video``), bind the oldest unbound video job to the short URL.

    Load-bearing assumption: a dedicated MJ channel + serial video submission
    (the /video route enforces one unbound video at a time via VIDEO_IN_FLIGHT).
    In a shared channel a foreign ``--video`` echo during the bind window could
    mis-bind — the same dedicated-channel premise the whole bridge runs under.
    """
    with LOCK:
        for job in JOBS.values():
            if job.kind == "video" and job.video_match_key and job.video_match_key in content:
                return job
        if not PENDING_VIDEO or "--video" not in content:
            return None
        m = _VIDEO_SHORT_URL_RE.search(content)
        if not m:
            return None
        # Bind the oldest LIVE pending video, popping past any dead entries
        # (terminal or evicted) first — defense in depth alongside the
        # terminal-transition cleanup, so a failed video can't poison the bind
        # of the next one. (review R2)
        while PENDING_VIDEO:
            cand = JOBS.get(PENDING_VIDEO.pop(0))
            if cand is None or cand.status in (Status.DONE, Status.FAILED):
                continue
            cand.video_match_key = m.group(1)
            cand.match_path = "video_bind"
            return cand
        return None


def _match_upscale(content: str) -> tuple[Job, int] | None:
    """Match an upscale-complete message to ``(parent_job, slot_index)``."""
    m = IMAGE_TAG_RE.search(content or "")
    if not m:
        return None
    idx = int(m.group(1))
    with LOCK:
        for job in JOBS.values():
            if job.status != Status.UPSCALING:
                continue
            if idx in job.upscale_paths or idx not in job.upscale_pending:
                continue
            if _token_needle(job.request_token) in content:
                return job, idx
    return None


def _find_job_by_idempotency_key(key: str) -> Job | None:
    """Return the newest live job created under ``key``, or None. Called under
    LOCK. O(n) over JOBS (bounded by MAX_JOBS) — no reverse index to drift out
    of sync with eviction/rehydration. Idempotency is naturally bounded by job
    retention: once a job is evicted, its key no longer dedups (standard
    idempotency-key expiry)."""
    for job in reversed(JOBS.values()):  # newest-first by insertion order
        if job.idempotency_key == key:
            return job
    return None


def _job_by_message_id(message_id: int) -> Job | None:
    with LOCK:
        for j in JOBS.values():
            if j.message_id == message_id:
                return j
    return None


def _video_result_parent(message_id: int) -> Job | None:
    """A **completed** native-video job whose result message a derived reply
    references — i.e. a ``video_virtual_upscale`` / ``reroll`` press fired AFTER
    the video finished, whose SOLO reply references the video result message.

    Must require ``status == DONE``: a native video's OWN final result also
    replies to its (progress) message, and that reply must flow through the
    completion path (VIDEO_RECEIVED), NOT be hijacked as a derived result. Only
    once the job is DONE is a further reply a genuine post-result action.
    (Caught live 2026-06-16: without the DONE gate the video's own result was
    routed to `derived` as a 'variation' and the job hung at 91%.) Image derived
    results reply to a SOLO upscale's ``upscale_message_id`` instead, so they
    never reach here."""
    with LOCK:
        for j in JOBS.values():
            if j.kind == "video" and j.status == Status.DONE and j.message_id == message_id:
                return j
    return None


def _job_by_upscale_message_id(message_id: int) -> Job | None:
    with LOCK:
        for j in JOBS.values():
            # Match the canonical SOLO or any per-slot SOLO (upscale="all" has
            # four), so a derived result replying to any of them routes home.
            if j.upscale_message_id == message_id or message_id in j.upscale_message_ids.values():
                return j
    return None

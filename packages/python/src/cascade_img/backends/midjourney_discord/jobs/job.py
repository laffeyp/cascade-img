"""The Job model, its status enum, prompt tagging, and table eviction.

Extracted from bridge.py (sprint 023.3). Sits above job_table.py (the shared
state) and persistence.py / config.py (read downward); below everything that
routes or ingests.
"""

from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass, field
from enum import StrEnum

from cascade_img.backends.midjourney_discord import config
from cascade_img.backends.midjourney_discord.jobs.job_table import (
    JOBS,
    PENDING_VIDEO,
    TERMINAL_CV,
)
from cascade_img.backends.midjourney_discord.jobs.persistence import _persist, _unpersist
from cascade_img.vocabulary import emit


class Status(StrEnum):
    QUEUED = "queued"  # accepted, not yet sent to Discord
    SUBMITTED = "submitted"  # /imagine fired, Discord ack'd, awaiting MJ message
    # Discord interaction POST timed out before returning. MJ may or may not
    # have processed the imagine. Job stays in PENDING_GRID so the grid-match
    # path still claims it if MJ comes through; /wait will resolve to DONE or
    # to the bridge-side wait-timeout, whichever lands first.
    SUBMITTED_UNCONFIRMED = "submitted_unconfirmed"
    PROGRESS = "progress"  # MJ is rendering the grid
    UPSCALING = "upscaling"  # grid done, awaiting U1-U4 results
    DONE = "done"
    FAILED = "failed"


# Capture the ``--no`` value up to (but not including) the next ``--flag`` or the
# end of string. The lookahead — rather than end-anchoring — stops a ``--no`` that
# sits mid-prompt from swallowing trailing flags like ``--ar``/``--s`` (which
# would otherwise be folded into the negative-prompt list). The ``(?!--)`` guard
# covers the degenerate case the lookahead alone misses: a value-less ``--no``
# immediately followed by a flag (``--no --ar 1:1``). Without it the value group
# would have to consume at least one char and would swallow ``--ar 1:1`` into the
# negative list, silently dropping the aspect ratio; with the guard the ``--no``
# simply doesn't match, the needle is appended as a fresh clause, and the real
# flag is left intact. The composer always emits ``--no`` last with a value, so
# it never triggers this; a hand-crafted raw prompt may.
_NO_CLAUSE_RE = re.compile(r"--no\s+(?!--)(.+?)(?=\s+--|\s*$)")


def _merge_no_clause(prompt: str, token: str) -> str:
    """Weave the per-job routing needle into the prompt's ``--no`` clause.

    The bridge routes MJ's echoed messages by finding ``cscidnocollide{token}``
    as a substring. If the prompt already contains a user ``--no`` clause (a
    negative prompt), append the needle to that one clause — MJ wants a single
    comma-separated ``--no`` list, and a second ``--no`` would break its parsing.
    Any flags that follow the ``--no`` clause are preserved in place. Otherwise
    add a fresh trailing ``--no`` clause. Either way the needle appears verbatim,
    so the matchers are unaffected.
    """
    needle = f"cscidnocollide{token}"
    m = _NO_CLAUSE_RE.search(prompt)
    if m:
        return f"{prompt[: m.start()]}--no {m.group(1)}, {needle}{prompt[m.end() :]}"
    return f"{prompt} --no {needle}"


@dataclass
class Job:
    job_id: str
    asset_id: str
    prompt: str
    # Per-job collision-free request token. Embedded into the prompt sent to
    # MJ as ``--no cscidnocollide{token}`` (a negative-prompt clause MJ
    # echoes verbatim without affecting rendering). _match_grid uses the
    # token instead of substring matching to avoid two-prompts-with-same-
    # prefix mis-routing.
    request_token: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    upscale: str | None = None  # None | "1".."4" | "all"
    # "image" (the default grid/upscale flow) or "video" (native `--video`
    # generation). A video job is routed by ``video_match_key`` (MJ's echoed
    # `s.mj.run/XXX` short URL — see F34 bind-on-vendor-echo) rather than the
    # `--no` request_token, because video prompts reject `--no`. Its final
    # artifact is one animated webp; it emits VIDEO_* instead of GRID_*.
    kind: str = "image"
    video_match_key: str | None = None
    status: Status = Status.QUEUED
    progress: str = ""
    message_id: int | None = None  # grid message id
    mj_job_uuid: str | None = None  # extracted from grid buttons
    image_path: str | None = None
    image_url: str | None = None
    grid_path: str | None = None
    grid_url: str | None = None
    # The SOLO upscaled-image message. MJ posts a fresh message per U-click,
    # and that message — not the grid — carries the vary / zoom / pan / animate
    # / favorite buttons. _ingest_message records it when an upscale lands so
    # POST /action/<job_id> can press those buttons by their live custom_id.
    upscale_message_id: int | None = None
    # Per-slot SOLO message ids (slot -> Discord message id). upscale="all"
    # produces four SOLO images, each its own actionable surface; this records
    # all of them so mj_action(slot=N) can target any, and derived-result
    # routing matches a reply to any of them. upscale_message_id stays the
    # canonical (image_path's slot) for mj_action's default target.
    upscale_message_ids: dict[int, int] = field(default_factory=dict)
    upscale_paths: dict[int, str] = field(default_factory=dict)
    upscale_pending: list[int] = field(default_factory=list)
    # Per-slot button-press failures (slot -> error message). During
    # upscale="all", individual U-button presses can fail while others succeed;
    # the job stays in UPSCALING and completes when surviving slots land. If
    # every requested slot's press fails, the job terminates with
    # UPSCALE_ALL_BUTTONS_FAILED. Empty when no presses failed.
    upscale_press_failures: dict[int, str] = field(default_factory=dict)
    # Per-slot upscale DOWNLOAD failures (slot -> error message). Mirrors
    # upscale_press_failures for the second failure surface: under upscale="all"
    # one slot's PNG download can fail while siblings land. The job stays
    # UPSCALING and completes on the surviving slots; only when no slot can land
    # (none downloaded, none still pending) does it terminate with
    # UPSCALE_DOWNLOAD_FAILED. Empty when no downloads failed.
    upscale_download_failures: dict[int, str] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    # Client-supplied idempotency key (optional). When a caller fires /imagine
    # with a key already attached to a live job, the bridge replays that job
    # instead of submitting again — closing the double-submit/double-bill window
    # a cancelled-mid-imagine MCP call can open (the orphaned worker-thread POST
    # lands, then the agent retries). Deliberately NOT keyed on asset_id: that
    # would reject legitimate regenerations. A retry must reuse the key to dedup; a
    # fresh generation gets a fresh key (or none) and a fresh job.
    idempotency_key: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # "pending" = matched while still in PENDING_GRID; "progress_fallback" =
    # matched after the job was already in PROGRESS (happens when MJ posts the
    # final grid as a new message instead of editing the initial preamble).
    match_path: str | None = None
    # Derived results (vary / zoom / pan / upscale-variant /
    # animation) pressed on this job's SOLO upscaled image. MJ posts each as a
    # Discord reply to upscale_message_id; the bridge downloads it and appends an
    # entry {action_kind, mj_uuid, message_id, path, url, content_type, width,
    # height, bytes}. Additive — the job is already DONE when these arrive.
    derived: list[dict] = field(default_factory=list)

    def tagged_prompt(self) -> str:
        """Outbound prompt with a per-job token MJ echoes back, used by
        :func:`_match_grid` to route MJ's messages without prefix collisions.
        """
        return _merge_no_clause(self.prompt, self.request_token)

    def touch(self) -> None:
        self.updated_at = time.time()
        _persist(self)

    def _fail(self, code: str, message: str) -> None:
        with TERMINAL_CV:
            self.status = Status.FAILED
            self.error_code = code
            self.error = message
            # A terminal video job must leave PENDING_VIDEO, or it poisons the
            # next video's bind-on-ack (the dead job would be popped and the new
            # video's result routed to it, then silently lost). Covers the reaper
            # path, which fails a timed-out video still in the queue. (review R2)
            if self.job_id in PENDING_VIDEO:
                PENDING_VIDEO.remove(self.job_id)
            self.touch()
            # A video job fails through its own incident tag (VIDEO_FAILED);
            # image/grid/upscale jobs fail through the generic JOB_FAILED.
            emit(
                "VIDEO_FAILED" if self.kind == "video" else "JOB_FAILED",
                asset_id=self.asset_id,
                job_id=self.job_id,
                error_code=code,
                error_message=message,
            )
            TERMINAL_CV.notify_all()

    def _complete(self) -> None:
        with TERMINAL_CV:
            self.status = Status.DONE
            self.progress = "100%"
            # Defensive: a bound video job already left PENDING_VIDEO at bind, but
            # keep the queue free of terminal ids regardless. (review R2)
            if self.job_id in PENDING_VIDEO:
                PENDING_VIDEO.remove(self.job_id)
            self.touch()
            emit(
                "JOB_COMPLETED",
                asset_id=self.asset_id,
                job_id=self.job_id,
                duration_ms=int((self.updated_at - self.created_at) * 1000),
                upscales_completed=len(self.upscale_paths),
            )
            TERMINAL_CV.notify_all()


def _evict_if_needed() -> None:
    """Drop terminal jobs older than TTL and evict the oldest terminal job
    when the dict exceeds capacity. Called under LOCK.
    """
    now = time.time()
    # TTL: drop terminal jobs older than TERMINAL_AGE_SECONDS.
    to_drop_ttl = [
        jid
        for jid, j in list(JOBS.items())
        if j.status in (Status.DONE, Status.FAILED)
        and (now - j.updated_at) > config.TERMINAL_AGE_SECONDS
    ]
    for jid in to_drop_ttl:
        j = JOBS.pop(jid, None)
        if j is not None:
            _unpersist(jid)
            emit(
                "JOB_EVICTED",
                asset_id=j.asset_id,
                job_id=j.job_id,
                reason="terminal_age_ttl",
                age_seconds=int(now - j.created_at),
                total_jobs_after=len(JOBS),
            )

    # LRU: evict oldest (in insertion order) while above capacity, but never
    # drop a non-terminal job (would orphan its waiter / its in-flight MJ
    # callback). If everyone's in-flight, the dict grows past cap — that's a
    # production signal (operator should slow submissions or raise MAX_JOBS).
    while len(JOBS) > config.MAX_JOBS:
        evicted_one = False
        for jid in list(JOBS.keys()):
            j = JOBS[jid]
            if j.status in (Status.DONE, Status.FAILED):
                JOBS.pop(jid, None)
                _unpersist(jid)
                emit(
                    "JOB_EVICTED",
                    asset_id=j.asset_id,
                    job_id=j.job_id,
                    reason="lru_capacity",
                    age_seconds=int(now - j.created_at),
                    total_jobs_after=len(JOBS),
                )
                evicted_one = True
                break
        if not evicted_one:
            break  # all over-cap jobs are in-flight; let it grow this round

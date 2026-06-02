"""
Midjourney -> local asset bridge for Cascade.

Pipeline shape:
    Claude (or any HTTP client)
        --POST /imagine {prompt, asset_id, upscale?}-->  this bridge (localhost:5000)
        <--{job_id}--

    Bridge fires Discord /imagine via interactions API as your user, watches the
    MJ channel via a self-bot WS connection, downloads the grid PNG when done,
    optionally presses U1-U4 to upscale, and writes results to ./generated/.

    Claude polls GET /status/<job_id> or long-polls GET /wait/<job_id>?timeout=120
    until status is "done" or "failed", then reads image_path.

Output naming:
    asset_id="relic_chip_v01", upscale=None   -> relic_chip_v01.png         (grid)
    asset_id="relic_chip_v01", upscale=1      -> relic_chip_v01.png         (U1)
                                                  relic_chip_v01_grid.png   (grid)
    asset_id="relic_chip_v01", upscale="all"  -> relic_chip_v01_u1.png ... _u4.png
                                                  relic_chip_v01_grid.png

----------------------------------------------------------------------
SETUP (do once)
----------------------------------------------------------------------

  pip install -U "discord.py-self" flask requests python-dotenv

  Copy .env.example -> .env and fill in DISCORD_USER_TOKEN, MJ_CHANNEL_ID,
  MJ_IMAGINE_VERSION, MJ_IMAGINE_COMMAND_ID, and MJ_GUILD_ID. See
  ``backends/midjourney_discord/__init__.py`` and the OPERATIONS doc for
  the devtools-capture procedure.

  Then run the daemon with the cascade-img CLI:
      cascade-mj-bridge

  Or call ``bridge.main()`` directly for an in-process embedding.

----------------------------------------------------------------------
SDD INSTRUMENTATION
----------------------------------------------------------------------

Every load-bearing state transition emits a signal via
:mod:`cascade_img.instrumentation.sdd`. The locked vocabulary lives at
``cascade_img/signals/versions/0.1.json``. The parity tool reads both and
asserts every emitted tag exists in the vocabulary; the daemon itself
never crashes over vocabulary drift. Read :func:`emit` call-sites bottom-up
to understand the daemon's contract — they are the contract.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import logging
import os
import re
import signal
import threading
import time
import uuid
from collections import OrderedDict
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path

import discord  # discord.py-self
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from cascade_img.instrumentation.sdd import emit

# Eviction configuration. Overridable via env at startup so deployments can
# tune for their own job-rate / memory profile.
MAX_JOBS = int(os.environ.get("CASCADE_MAX_JOBS", "1000"))
TERMINAL_AGE_SECONDS = float(os.environ.get("CASCADE_TERMINAL_AGE_SECONDS", "3600"))


PACKAGE_VERSION = "0.1.0"  # bumped in lock-step with pyproject.toml
BACKEND_NAME = "midjourney_discord"


# ---------------------------------------------------------------------------
# Config + structured error
# ---------------------------------------------------------------------------
#
# The seven environment-derived values used to be read at module import time
# (``DISCORD_TOKEN = os.environ["DISCORD_USER_TOKEN"]`` etc.). That worked as a
# script but made the module unimportable in any context without a full live
# .env on disk — and a missing var raised a bare KeyError with no remediation.
#
# Now they live on a Config dataclass. ``Config.from_env`` validates each
# required var and raises :class:`MissingEnvError` carrying a stable code
# string and a human-readable remediation pointing at the operations doc.
# The ``MJ_GUILD_ID`` trap from Sprint 4.0 is the worked example: the
# original failure surfaced as ``discord 400: Unknown Channel`` (an LLM
# operator can't recover); the remediated failure is
# ``{"code": "MISSING_GUILD_ID", "remediation": "..."}`` (recoverable).
#
# ``MJ_BOT_ID`` stays a module constant — it's the Midjourney bot's Discord
# application ID, not a per-deployment value.

MJ_BOT_ID = 936929561302675456


class MissingEnvError(Exception):
    """A required environment variable is missing or wrong-shaped.

    Carries a stable error ``code`` an LLM operator can branch on, and a
    human-readable ``remediation`` pointing at the operations doc.
    """

    def __init__(self, code: str, message: str, remediation: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.remediation = remediation

    def to_payload(self) -> dict:
        return {
            "code": self.code,
            "message": self.message,
            "remediation": self.remediation,
        }


@dataclass
class Config:
    """All deployment-specific configuration for the MJ-via-Discord daemon."""

    discord_token: str
    channel_id: int
    guild_id: str | None              # required when MJ channel lives in a guild — Sprint 4.0 patch
    mj_imagine_version: str
    mj_imagine_command_id: str
    output_dir: Path
    port: int

    @classmethod
    def from_env(cls) -> Config:
        """Read and validate every env var; raise MissingEnvError on the first gap."""
        load_dotenv()

        def _require(name: str, code: str, remediation: str) -> str:
            val = os.environ.get(name)
            if not val:
                raise MissingEnvError(
                    code,
                    f"environment variable {name} is not set",
                    remediation,
                )
            return val

        discord_token = _require(
            "DISCORD_USER_TOKEN",
            "MISSING_DISCORD_TOKEN",
            "Add DISCORD_USER_TOKEN to .env; see OPERATIONS.md §setup §4 for the "
            "devtools-capture procedure. Treat the value as a password.",
        )
        channel_id_raw = _require(
            "MJ_CHANNEL_ID",
            "MISSING_CHANNEL_ID",
            "Add MJ_CHANNEL_ID to .env. Enable Discord Developer Mode "
            "(Settings -> Advanced) then right-click the MJ channel -> Copy Channel ID.",
        )
        try:
            channel_id = int(channel_id_raw)
        except ValueError as e:
            raise MissingEnvError(
                "INVALID_CHANNEL_ID",
                f"MJ_CHANNEL_ID is not a valid integer: {channel_id_raw!r}",
                "MJ_CHANNEL_ID must be the 18-19 digit channel ID from Discord. "
                "Re-capture per OPERATIONS.md §setup §4.",
            ) from e

        # MJ_GUILD_ID is the Sprint 4.0 patch — required whenever the MJ
        # channel lives in a guild. Upstream omitted it, which made every
        # initial /imagine fail with Discord 400 "Unknown Channel". We tolerate
        # absence (DM-only deployments) but warn loudly so the override is
        # intentional, not silent.
        guild_id = os.environ.get("MJ_GUILD_ID") or None

        mj_imagine_version = _require(
            "MJ_IMAGINE_VERSION",
            "MISSING_IMAGINE_VERSION",
            "Add MJ_IMAGINE_VERSION to .env. Re-capture from desktop Discord "
            "DevTools whenever MJ updates the slash command (you'll see "
            "'discord 400: This command is outdated'). See OPERATIONS.md §setup §4.",
        )
        mj_imagine_command_id = os.environ.get(
            "MJ_IMAGINE_COMMAND_ID", "938956540159881230"
        )

        output_dir = Path(os.environ.get("MJ_OUTPUT_DIR", "./generated")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            port = int(os.environ.get("PORT", "5000"))
            if not (1 <= port <= 65535):
                raise ValueError(f"port must be 1-65535, got {port}")
        except ValueError as e:
            raise MissingEnvError(
                "INVALID_PORT",
                f"PORT must be a valid integer 1-65535: {os.environ.get('PORT')!r}",
                "PORT defaults to 5000. Set a positive integer 1-65535 or leave unset.",
            ) from e

        emit(
            "CONFIG_VALIDATED",
            port=port,
            output_dir=str(output_dir),
            has_guild_id=bool(guild_id),
        )
        return cls(
            discord_token=discord_token,
            channel_id=channel_id,
            guild_id=guild_id,
            mj_imagine_version=mj_imagine_version,
            mj_imagine_command_id=mj_imagine_command_id,
            output_dir=output_dir,
            port=port,
        )


# Module-level Config holder. Set by :func:`main` (or by an embedding caller)
# before the Discord event loop or Flask app are started.
cfg: Config | None = None


def _cfg() -> Config:
    """Return the loaded Config, asserting it was set at startup."""
    if cfg is None:
        raise RuntimeError(
            "bridge.cfg is not set — call Config.from_env() and assign to "
            "module-level cfg before starting the daemon."
        )
    return cfg


# Module-level logger only. ``logging.basicConfig`` is NOT called here — that
# would clobber configuration done by embedding callers (a host that imports
# this module to drive the bridge in-process should own its logging config).
# The ``cascade-mj-bridge`` CLI's ``main()`` calls basicConfig when it owns
# the process; everywhere else, the logger inherits the consumer's config.
log = logging.getLogger("cascade_img.bridge")


# ---------------------------------------------------------------------------
# Job model
# ---------------------------------------------------------------------------


class Status(str, Enum):
    QUEUED = "queued"          # accepted, not yet sent to Discord
    SUBMITTED = "submitted"    # /imagine fired, awaiting MJ message
    PROGRESS = "progress"      # MJ is rendering the grid
    UPSCALING = "upscaling"    # grid done, awaiting U1-U4 results
    DONE = "done"
    FAILED = "failed"


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
    upscale: str | None = None              # None | "1".."4" | "all"
    status: Status = Status.QUEUED
    progress: str = ""
    message_id: int | None = None           # grid message id
    mj_job_uuid: str | None = None          # extracted from grid buttons
    image_path: str | None = None           # canonical output path
    image_url: str | None = None
    grid_path: str | None = None
    grid_url: str | None = None
    upscale_paths: dict = field(default_factory=dict)
    upscale_pending: list = field(default_factory=list)
    error: str | None = None
    error_code: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # SDD-specific: which path _match_grid took ("pending" first-touch vs
    # "progress_fallback" — the Sprint 4.0 V7 patch path).
    match_path: str | None = None

    def tagged_prompt(self) -> str:
        """Return the prompt with the unique collision-resistant token
        appended as ``--no cscidnocollide{token}`` so MJ echoes it back."""
        return f"{self.prompt} --no cscidnocollide{self.request_token}"

    def touch(self):
        self.updated_at = time.time()

    def _fail(self, code: str, message: str) -> None:
        # Acquire LOCK (RLock — safe even when caller already holds it) and
        # notify TERMINAL_CV so any /wait blocked on this job wakes immediately.
        with TERMINAL_CV:
            self.status = Status.FAILED
            self.error_code = code
            self.error = message
            self.touch()
            emit(
                "JOB_FAILED",
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
            self.touch()
            emit(
                "JOB_COMPLETED",
                asset_id=self.asset_id,
                job_id=self.job_id,
                duration_ms=int((self.updated_at - self.created_at) * 1000),
                upscales_completed=len(self.upscale_paths),
            )
            TERMINAL_CV.notify_all()


# OrderedDict so the LRU eviction can drop the oldest job on overflow.
JOBS: OrderedDict[str, Job] = OrderedDict()
PENDING_GRID: list[str] = []  # job_ids awaiting grid message match, FIFO
# RLock + Condition so /wait can sleep on a job-terminal notification rather
# than polling the dict, AND so the inner mutation helpers (job._complete /
# job._fail) can acquire the lock even when a caller already holds it.
LOCK = threading.RLock()
TERMINAL_CV = threading.Condition(LOCK)


def _evict_if_needed() -> None:
    """Run LRU + TTL eviction under LOCK. Called on every JOBS insertion and
    on each /wait wake-up. Emits :data:`JOB_EVICTED` for every dropped job.
    """
    now = time.time()
    # TTL: drop terminal jobs older than TERMINAL_AGE_SECONDS.
    to_drop_ttl = [
        jid for jid, j in list(JOBS.items())
        if j.status in (Status.DONE, Status.FAILED)
        and (now - j.updated_at) > TERMINAL_AGE_SECONDS
    ]
    for jid in to_drop_ttl:
        j = JOBS.pop(jid, None)
        if j is not None:
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
    while len(JOBS) > MAX_JOBS:
        evicted_one = False
        for jid in list(JOBS.keys()):
            j = JOBS[jid]
            if j.status in (Status.DONE, Status.FAILED):
                JOBS.pop(jid, None)
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

UPSAMPLE_BTN_RE = re.compile(r"MJ::JOB::upsample::(\d+)::([0-9a-f-]+)")
IMAGE_TAG_RE = re.compile(r"Image #(\d+)")
PCT_RE = re.compile(r"\((\d+)%\)")


# ---------------------------------------------------------------------------
# Discord side
# ---------------------------------------------------------------------------

client = discord.Client()
_loop_holder: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}
_ready = threading.Event()


@client.event
async def on_ready():
    c = _cfg()
    log.info(f"Discord connected as {client.user} (id={client.user.id})")
    log.info(f"Watching channel {c.channel_id}")
    emit("DISCORD_CONNECTED", user_id=str(client.user.id))
    _ready.set()


def _token_needle(token: str) -> str:
    """The substring _match_grid looks for in MJ's echoed content.

    Per-job request tokens are appended to the outbound prompt as
    ``--no cscidnocollide{token}``; MJ's progress and grid messages echo
    the prompt verbatim, so finding ``cscidnocollide{token}`` in the
    content is a collision-free routing key.
    """
    return f"cscidnocollide{token}"


def _match_grid(content: str) -> Job | None:
    """Find the pending grid job whose request token appears in MJ's message.

    Two paths:
    1) Job still in PENDING_GRID — first-touch match (typically MJ's initial
       prompt-echo / "Waiting to start" message). Sets ``job.match_path = "pending"``.
    2) Job already in PROGRESS — modern MJ v7 posts the completed grid as a
       SEPARATE new message (different ID) rather than editing the original.
       Without this fallback the final grid is ignored and the job stalls at
       PROGRESS forever. This is one of the two Sprint-4.0 production patches.
       Sets ``job.match_path = "progress_fallback"``.

    The collision-resistant request_token (added Sprint 008) replaces the
    earlier prompt-prefix-substring approach, which could mis-route between
    jobs sharing a common prefix.
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
            if job.status != Status.PROGRESS:
                continue
            if job.grid_path is not None:
                continue  # already saved; don't re-match
            if _token_needle(job.request_token) in content and "Image #" not in content:
                job.match_path = "progress_fallback"
                return job
    return None


def _match_upscale(content: str) -> tuple[Job, int] | None:
    """Match an upscale completion message to (parent_job, slot_index)."""
    m = IMAGE_TAG_RE.search(content or "")
    if not m:
        return None
    idx = int(m.group(1))
    with LOCK:
        for job in JOBS.values():
            if job.status != Status.UPSCALING:
                continue
            if idx in job.upscale_paths:
                continue
            if idx not in job.upscale_pending:
                continue
            # Token-based match (added Sprint 008) — same collision avoidance
            # as _match_grid.
            if _token_needle(job.request_token) in content:
                return job, idx
    return None


def _job_by_message_id(message_id: int) -> Job | None:
    with LOCK:
        for j in JOBS.values():
            if j.message_id == message_id:
                return j
    return None


def _download_to(url: str, path: Path) -> int:
    # Use a stream + with-statement so the Response is closed deterministically
    # rather than leaving it to GC — review-flagged 2026-06-02 (connection-pool
    # exhaustion on a long-running bridge).
    with requests.get(url, timeout=30, stream=True) as resp:
        resp.raise_for_status()
        data = resp.content
    path.write_bytes(data)
    return len(data)


def _extract_mj_uuid(components) -> str | None:
    """Pull the MJ job UUID out of any upsample button in the message."""
    for row in components or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            m = UPSAMPLE_BTN_RE.search(cid)
            if m:
                return m.group(2)
    return None


def _ingest_message(message):
    """Update job state from an MJ message (new or edited)."""
    c = _cfg()
    if message.author.id != MJ_BOT_ID or message.channel.id != c.channel_id:
        return

    content = message.content or ""

    # --- Path A: this is a grid message for an in-flight job ---
    job = _job_by_message_id(message.id)
    if job is None:
        job = _match_grid(content)
        if job is not None:
            # Mutate the matched job under LOCK so /status / /jobs HTTP routes
            # don't see torn state. Review-flagged 2026-06-02.
            with LOCK:
                job.message_id = message.id
                job.status = Status.PROGRESS
                job.touch()
            log.info(
                f"[{job.asset_id}] matched grid message {message.id} "
                f"via {job.match_path}"
            )
            emit(
                "GRID_MATCHED",
                asset_id=job.asset_id,
                job_id=job.job_id,
                message_id=message.id,
                match_path=job.match_path or "unknown",
            )

    if job is not None and job.status in (Status.PROGRESS, Status.SUBMITTED):
        pct = PCT_RE.search(content)
        if pct:
            job.progress = f"{pct.group(1)}%"
            job.touch()
            return
        if "(Waiting to start)" in content:
            job.progress = "queued"
            job.touch()
            return
        if message.attachments:
            # Grid complete.
            att = message.attachments[0]
            job.grid_url = att.url
            ext = os.path.splitext(att.filename)[1] or ".png"
            try:
                if job.upscale:
                    grid_path = c.output_dir / f"{job.asset_id}_grid{ext}"
                else:
                    grid_path = c.output_dir / f"{job.asset_id}{ext}"
                grid_bytes = _download_to(att.url, grid_path)
                job.grid_path = str(grid_path)
                emit(
                    "GRID_RECEIVED",
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    path=str(grid_path),
                    bytes=grid_bytes,
                )
                if not job.upscale:
                    job.image_path = str(grid_path)
                    job.image_url = att.url
                    log.info(f"[{job.asset_id}] saved grid -> {grid_path}")
                    job._complete()
                    return
            except Exception as e:
                job._fail("GRID_DOWNLOAD_FAILED", f"grid download failed: {e}")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            # Upscale requested. Extract MJ job uuid, fire button presses.
            job.mj_job_uuid = _extract_mj_uuid(message.components)
            if not job.mj_job_uuid:
                job._fail("MJ_UUID_MISSING", "could not find MJ job uuid in grid components")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            slots = [1, 2, 3, 4] if job.upscale == "all" else [int(job.upscale)]
            job.upscale_pending = list(slots)
            job.status = Status.UPSCALING
            job.progress = "upscaling"
            job.touch()
            log.info(
                f"[{job.asset_id}] grid done, requesting upscale "
                f"slots={slots} mj_uuid={job.mj_job_uuid[:8]}..."
            )

            guild_id = str(message.guild.id) if message.guild else None
            for n in slots:
                custom_id = f"MJ::JOB::upsample::{n}::{job.mj_job_uuid}"
                emit(
                    "UPSCALE_REQUESTED",
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    slot=n,
                    mj_job_uuid_prefix=job.mj_job_uuid[:8],
                )
                fut = asyncio.run_coroutine_threadsafe(
                    _press_button(message.id, custom_id, guild_id),
                    _loop_holder["loop"],
                )
                try:
                    resp = fut.result(timeout=20)
                    if resp.status_code not in (200, 204):
                        log.error(
                            f"[{job.asset_id}] U{n} press failed: "
                            f"{resp.status_code} {resp.text[:200]}"
                        )
                except Exception as e:
                    log.error(f"[{job.asset_id}] U{n} press exception: {e}")
            return

    # --- Path B: this might be an upscale completion message ---
    matched = _match_upscale(content)
    if matched and message.attachments:
        parent, idx = matched
        att = message.attachments[0]
        ext = os.path.splitext(att.filename)[1] or ".png"
        try:
            if parent.upscale == "all":
                out_path = c.output_dir / f"{parent.asset_id}_u{idx}{ext}"
            else:
                out_path = c.output_dir / f"{parent.asset_id}{ext}"
            up_bytes = _download_to(att.url, out_path)
            # All post-download mutations under LOCK so the concurrent
            # "two messages for the same slot" race can't crash with
            # ValueError on list.remove, and /status reads don't see
            # half-updated parent. Review-flagged 2026-06-02.
            with LOCK:
                parent.upscale_paths[idx] = str(out_path)
                if parent.image_path is None:
                    # First upscale wins canonical slot
                    parent.image_path = str(out_path)
                    parent.image_url = att.url
                if idx in parent.upscale_pending:
                    parent.upscale_pending.remove(idx)
                parent.touch()
            log.info(f"[{parent.asset_id}] saved upscale U{idx} -> {out_path}")
            emit(
                "UPSCALE_RECEIVED",
                asset_id=parent.asset_id,
                job_id=parent.job_id,
                slot=idx,
                path=str(out_path),
                bytes=up_bytes,
            )
            if not parent.upscale_pending:
                log.info(f"[{parent.asset_id}] all upscales complete")
                parent._complete()
        except Exception as e:
            parent._fail(
                "UPSCALE_DOWNLOAD_FAILED",
                f"upscale U{idx} download failed: {e}",
            )
            log.error(f"[{parent.asset_id}] {parent.error}")


@client.event
async def on_message(message):
    # _ingest_message does blocking I/O (downloads PNGs, button-press HTTP).
    # Dispatch it to the default thread pool so it doesn't stall the Discord
    # event loop while a 30s grid download runs.
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ingest_message, message)


@client.event
async def on_message_edit(before, after):
    loop = asyncio.get_event_loop()
    await loop.run_in_executor(None, _ingest_message, after)


async def _post_interaction(payload: dict) -> requests.Response:
    c = _cfg()
    headers = {"Authorization": c.discord_token, "Content-Type": "application/json"}
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(
        None,
        lambda: requests.post(
            "https://discord.com/api/v9/interactions",
            json=payload,
            headers=headers,
            timeout=20,
        ),
    )


async def _send_imagine(prompt: str) -> requests.Response:
    """Fire /imagine to MJ via the Discord interactions API.

    The ``payload["guild_id"] = cfg.guild_id`` line is the second Sprint-4.0
    production patch. Upstream omitted ``guild_id`` from the interaction
    payload, which made Discord treat the call as a DM and return
    ``discord 400: Unknown Channel, code 10003`` for any guild-channel ID. Do
    not remove without re-validating against a live guild-hosted MJ channel.
    """
    c = _cfg()
    payload = {
        "type": 2,
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(c.channel_id),
        "session_id": client.ws.session_id,
        "data": {
            "version": c.mj_imagine_version,
            "id": c.mj_imagine_command_id,
            "name": "imagine",
            "type": 1,
            "options": [{"type": 3, "name": "prompt", "value": prompt}],
            "application_command": {
                "id": c.mj_imagine_command_id,
                "application_id": str(MJ_BOT_ID),
                "version": c.mj_imagine_version,
                "name": "imagine",
                "type": 1,
                "options": [
                    {"type": 3, "name": "prompt", "description": "The prompt to imagine"}
                ],
            },
        },
    }
    if c.guild_id:
        payload["guild_id"] = c.guild_id
    return await _post_interaction(payload)


async def _press_button(
    message_id: int, custom_id: str, guild_id: str | None
) -> requests.Response:
    c = _cfg()
    payload = {
        "type": 3,  # MESSAGE_COMPONENT
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(c.channel_id),
        "message_id": str(message_id),
        "session_id": client.ws.session_id,
        "data": {
            "component_type": 2,
            "custom_id": custom_id,
        },
    }
    if guild_id:
        payload["guild_id"] = guild_id
    return await _post_interaction(payload)


# ---------------------------------------------------------------------------
# Flask side
# ---------------------------------------------------------------------------

app = Flask(__name__)


def _normalize_upscale(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool):  # True -> "1" so curl users can pass true
        return "1" if value else None
    s = str(value).strip().lower()
    if s in ("", "false", "none", "null"):
        return None
    if s == "all":
        return "all"
    if s in ("1", "2", "3", "4"):
        return s
    raise ValueError(f"upscale must be None, 1-4, or 'all'; got {value!r}")


@app.post("/imagine")
def http_imagine():
    if not _ready.is_set():
        return jsonify(error="discord client not ready yet, retry in a few seconds"), 503

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify(error="missing 'prompt'"), 400

    try:
        upscale = _normalize_upscale(body.get("upscale"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    asset_id_raw = body.get("asset_id") or f"asset_{uuid.uuid4().hex[:8]}"
    asset_id = "".join(
        c if c.isalnum() or c in "._-" else "_" for c in str(asset_id_raw)
    )[:80]

    job = Job(
        job_id=uuid.uuid4().hex,
        asset_id=asset_id,
        prompt=prompt,
        upscale=upscale,
    )
    with LOCK:
        JOBS[job.job_id] = job
        PENDING_GRID.append(job.job_id)
        _evict_if_needed()

    # Send the TAGGED prompt to MJ (includes the per-job request_token via
    # --no cscidnocollide{token}). _match_grid will look for the same token
    # in MJ's echoed content. The original prompt is preserved in job.prompt
    # for the log/audit trail.
    fut = asyncio.run_coroutine_threadsafe(_send_imagine(job.tagged_prompt()), _loop_holder["loop"])
    try:
        resp = fut.result(timeout=20)
    except Exception as e:
        job._fail("SUBMIT_FAILED", f"submit failed: {e}")
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        return jsonify(error=str(e), job_id=job.job_id), 502

    if resp.status_code not in (200, 204):
        # Map known Discord failures to stable error codes so an LLM operator
        # can branch deterministically.
        text = resp.text[:200]
        if resp.status_code == 401:
            code = "DISCORD_401"
        elif "outdated" in text.lower():
            code = "DISCORD_400_OUTDATED"
        elif "unknown channel" in text.lower():
            code = "DISCORD_400_UNKNOWN_CHANNEL"
        else:
            code = f"DISCORD_{resp.status_code}"
        job._fail(code, f"discord {resp.status_code}: {text}")
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        log.error(f"[{job.asset_id}] {job.error}")
        return jsonify(error=job.error, job_id=job.job_id), 502

    job.status = Status.SUBMITTED
    job.touch()
    log.info(
        f"[{job.asset_id}] submitted: upscale={upscale or '-'} prompt={prompt[:80]}"
    )
    emit(
        "IMAGINE_FIRED",
        asset_id=job.asset_id,
        job_id=job.job_id,
        prompt_chars=len(prompt),
        upscale=upscale,
    )
    return jsonify(
        job_id=job.job_id, asset_id=job.asset_id, status=job.status, upscale=upscale
    )


@app.get("/status/<job_id>")
def http_status(job_id):
    job = JOBS.get(job_id)
    if not job:
        return jsonify(error="unknown job_id"), 404
    return jsonify(asdict(job))


@app.get("/wait/<job_id>")
def http_wait(job_id):
    """Block on TERMINAL_CV until the job hits done/failed or the timeout
    fires. No per-request polling thread tied up sleeping — the Flask thread
    parks on the condition and is woken by job._complete / job._fail.
    """
    timeout = float(request.args.get("timeout", "120"))
    deadline = time.time() + timeout
    with TERMINAL_CV:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="unknown job_id"), 404
        while job.status not in (Status.DONE, Status.FAILED):
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            TERMINAL_CV.wait(timeout=remaining)
            job = JOBS.get(job_id)
            if not job:
                # Could be evicted during the wait (unlikely; LRU avoids
                # in-flight). Treat as 410 Gone.
                return jsonify(error="job evicted during wait"), 410
        if job.status in (Status.DONE, Status.FAILED):
            return jsonify(asdict(job))
        payload = asdict(job)
        payload["timed_out"] = True
        return jsonify(payload), 504


@app.get("/jobs")
def http_jobs():
    with LOCK:
        return jsonify([asdict(j) for j in JOBS.values()])


@app.get("/health")
def http_health():
    c = _cfg()
    discord_ready = _ready.is_set()
    pending = len(PENDING_GRID)
    total = len(JOBS)
    emit(
        "BRIDGE_HEALTHY",
        discord_ready=discord_ready,
        pending_grid=pending,
        total_jobs=total,
    )
    return jsonify(
        discord_ready=discord_ready,
        pending_grid=pending,
        upscaling=sum(1 for j in JOBS.values() if j.status == Status.UPSCALING),
        total_jobs=total,
        output_dir=str(c.output_dir),
    )


def _run_discord():
    c = _cfg()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop_holder["loop"] = loop
    loop.run_until_complete(client.start(c.discord_token))


# ---------------------------------------------------------------------------
# CLI subcommands: --check-env, --doctor, default daemon run
# ---------------------------------------------------------------------------


def check_env() -> dict:
    """Validate the environment without starting anything. Returns a
    structured dict with ``ok`` and either ``config`` (the loaded fields,
    secrets masked) or ``error`` (code + remediation).
    """

    try:
        c = Config.from_env()
    except MissingEnvError as e:
        emit(
            "BRIDGE_CHECKENV_RAN",
            ok=False,
            error_code=e.code,
        )
        return {
            "ok": False,
            "error": e.to_payload(),
        }
    emit("BRIDGE_CHECKENV_RAN", ok=True, error_code="")
    return {
        "ok": True,
        "config": {
            # mask the token by length so the operator can see something is
            # there without leaking it
            "discord_token_present": bool(c.discord_token),
            "discord_token_len": len(c.discord_token),
            "channel_id": c.channel_id,
            "guild_id": c.guild_id,
            "mj_imagine_version": c.mj_imagine_version,
            "mj_imagine_command_id": c.mj_imagine_command_id,
            "output_dir": str(c.output_dir),
            "port": c.port,
        },
    }


def doctor() -> dict:
    """Full validation: env, Discord API reachability, MCP server importable,
    bridge-side imports clean. Returns a list of checks with per-check
    pass/fail/remediation.

    Does NOT start the daemon or connect to Discord — those are side-effecty
    and require live MJ. Use ``--doctor`` for the pre-flight; use the running
    daemon's ``/health`` for live-state.
    """
    checks: list[dict] = []

    # check 1: env
    env_result = check_env()
    checks.append(
        {
            "name": "env",
            "ok": env_result["ok"],
            **({"detail": env_result["config"]} if env_result["ok"] else {"error": env_result["error"]}),
        }
    )

    # check 2: discord.com reachability (no token needed; just network)
    try:
        r = requests.get("https://discord.com/api/v9/gateway", timeout=5)
        checks.append(
            {
                "name": "discord_reachable",
                "ok": r.status_code == 200,
                "status": r.status_code,
            }
        )
    except Exception as e:
        checks.append(
            {
                "name": "discord_reachable",
                "ok": False,
                "error": {"code": "DISCORD_UNREACHABLE", "message": str(e)},
            }
        )

    # check 3: MCP server module imports
    try:
        import importlib
        importlib.import_module("cascade_img.mcp_server")
        checks.append({"name": "mcp_server_importable", "ok": True})
    except Exception as e:
        checks.append(
            {
                "name": "mcp_server_importable",
                "ok": False,
                "error": {"code": "MCP_IMPORT_FAILED", "message": str(e)},
            }
        )

    # check 4: discord.py-self importable (catches Python-version mismatch)
    try:
        import importlib
        importlib.import_module("discord")
        checks.append({"name": "discord_self_importable", "ok": True})
    except Exception as e:
        checks.append(
            {
                "name": "discord_self_importable",
                "ok": False,
                "error": {"code": "DISCORD_SELF_IMPORT_FAILED", "message": str(e)},
            }
        )

    ok = all(c["ok"] for c in checks)
    emit("BRIDGE_DOCTOR_RAN", ok=ok, checks_total=len(checks),
         checks_failed=sum(1 for c in checks if not c["ok"]))
    return {"ok": ok, "checks": checks}


_shutdown_emitted = False


def _emit_shutdown(reason: str) -> None:
    """Idempotent BRIDGE_SHUTDOWN emit. atexit + signal handlers both call
    this; whichever runs first wins."""
    global _shutdown_emitted
    if _shutdown_emitted:
        return
    _shutdown_emitted = True
    # Shutdown hook must never propagate — swallow any signal-emission error.
    with contextlib.suppress(Exception):
        emit("BRIDGE_SHUTDOWN", reason=reason)


def _signal_handler(signum, _frame):
    name = signal.Signals(signum).name if isinstance(signum, int) else str(signum)
    _emit_shutdown(f"signal:{name}")
    raise SystemExit(0)


def main() -> None:
    """Entrypoint for the ``cascade-mj-bridge`` console script.

    Subcommands:
      (no flags)        Run the daemon.
      --check-env       Validate config; emit JSON; exit 0/1.
      --doctor          Full pre-flight (env + reachability + imports); JSON; exit 0/1.
    """
    import json as _json
    import sys

    # The CLI owns the process — configure root logging here, not at module
    # import time (which would clobber embedding callers' logging config).
    if not logging.getLogger().handlers:
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )

    # BRIDGE_SHUTDOWN: register both atexit and signal handlers so the signal
    # fires reliably on SIGINT/SIGTERM and atexit catches the rare normal-exit
    # path.
    atexit.register(_emit_shutdown, "atexit")
    try:
        signal.signal(signal.SIGINT, _signal_handler)
        signal.signal(signal.SIGTERM, _signal_handler)
    except (ValueError, OSError):
        # Non-main-thread or platform without signal support — atexit catches it.
        pass

    parser = argparse.ArgumentParser(prog="cascade-mj-bridge")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument("--check-env", action="store_true",
                     help="Validate config and exit. JSON to stdout.")
    grp.add_argument("--doctor", action="store_true",
                     help="Full pre-flight check (env + reachability + imports). JSON to stdout.")
    parser.add_argument("--pretty", action="store_true",
                        help="Indent JSON output (--check-env / --doctor only).")
    args = parser.parse_args()

    if args.check_env:
        result = check_env()
        print(_json.dumps(result, indent=2 if args.pretty else None))
        sys.exit(0 if result["ok"] else 1)

    if args.doctor:
        result = doctor()
        print(_json.dumps(result, indent=2 if args.pretty else None))
        sys.exit(0 if result["ok"] else 1)

    # Default: run the daemon.
    global cfg
    try:
        cfg = Config.from_env()
    except MissingEnvError as e:
        emit(
            "CONFIG_VALIDATION_FAILED",
            code=e.code,
            field=e.message,
            remediation=e.remediation,
        )
        # Re-raise so the CLI surfaces a non-zero exit; structured payload
        # is reachable via --check-env / --doctor.
        raise

    emit("CASCADE_INIT", package_version=PACKAGE_VERSION, backend=BACKEND_NAME)

    t = threading.Thread(target=_run_discord, daemon=True)
    t.start()
    while _loop_holder["loop"] is None:
        time.sleep(0.05)
    log.info(f"HTTP bridge listening on http://127.0.0.1:{cfg.port}")
    app.run(host="127.0.0.1", port=cfg.port, threaded=True)


if __name__ == "__main__":
    main()

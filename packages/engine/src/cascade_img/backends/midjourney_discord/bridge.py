"""Midjourney bridge daemon.

A Flask service that drives Midjourney from a Discord user account.

    POST /imagine {prompt, asset_id, upscale?} -> {job_id}
    GET  /status/<job_id>                      -> job record
    GET  /wait/<job_id>?timeout=120            -> blocks until done/failed
    GET  /jobs                                 -> all jobs
    GET  /health                               -> daemon + Discord status

The daemon fires ``/imagine`` as a Discord interaction, watches the MJ
channel via WebSocket, downloads the grid when MJ posts it, optionally
presses U1-U4 to upscale, and writes PNGs under ``MJ_OUTPUT_DIR``.

Output filenames (asset_id = ``a``)::

    upscale=None       a.{png,webp}
    upscale=1|2|3|4    a.png + a_grid.{png,webp}
    upscale="all"      a_u1.png .. a_u4.png + a_grid.{png,webp}

Run with ``cascade-mj-bridge``; embed by calling :func:`main`.
"""

from __future__ import annotations

import argparse
import asyncio
import atexit
import contextlib
import importlib
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

from cascade_img.vocabulary import emit

# Eviction configuration. Overridable via env at startup so deployments can
# tune for their own job-rate / memory profile.
MAX_JOBS = int(os.environ.get("CASCADE_MAX_JOBS", "1000"))
TERMINAL_AGE_SECONDS = float(os.environ.get("CASCADE_TERMINAL_AGE_SECONDS", "3600"))


PACKAGE_VERSION = "0.1.0"  # bumped in lock-step with pyproject.toml
BACKEND_NAME = "midjourney_discord"


# Midjourney bot's Discord application ID. Constant across all deployments.
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


class DiscordNotReadyError(Exception):
    """The Discord WebSocket is not in a state where an interaction call would
    succeed (no session_id available). Distinct from MissingEnvError so the
    Flask layer can return 503 with a structured retryable-error envelope.
    """

    code = "DISCORD_NOT_READY"
    remediation = (
        "Wait for the bridge's reconnect loop to re-establish the gateway "
        "session. Check GET /health for discord_ready=true; the daemon will "
        "back off and retry automatically unless DISCORD_RECONNECT_FAILED was "
        "emitted (terminal auth failure — operator must rotate the token)."
    )

    def __init__(self, detail: str) -> None:
        super().__init__(f"Discord client not ready: {detail}")
        self.detail = detail


@dataclass
class Config:
    """Daemon configuration. Constructed via :meth:`from_env`."""

    discord_token: str
    channel_id: int
    # Required when the MJ channel lives in a guild; Discord 400s otherwise.
    guild_id: str | None
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
            "Add DISCORD_USER_TOKEN to .env; see RUNBOOK.md for the "
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
                "Re-capture per RUNBOOK.md.",
            ) from e

        # Optional: required only when the MJ channel lives in a guild.
        guild_id = os.environ.get("MJ_GUILD_ID") or None

        mj_imagine_version = _require(
            "MJ_IMAGINE_VERSION",
            "MISSING_IMAGINE_VERSION",
            "Add MJ_IMAGINE_VERSION to .env. Re-capture from desktop Discord "
            "DevTools whenever MJ updates the slash command (you'll see "
            "'discord 400: This command is outdated'). See RUNBOOK.md.",
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
    SUBMITTED = "submitted"    # /imagine fired, Discord ack'd, awaiting MJ message
    # Discord interaction POST timed out before returning. MJ may or may not
    # have processed the imagine. Job stays in PENDING_GRID so the grid-match
    # path still claims it if MJ comes through; /wait will resolve to DONE or
    # to the bridge-side wait-timeout, whichever lands first.
    SUBMITTED_UNCONFIRMED = "submitted_unconfirmed"
    PROGRESS = "progress"      # MJ is rendering the grid
    UPSCALING = "upscaling"    # grid done, awaiting U1-U4 results
    DONE = "done"
    FAILED = "failed"


_NO_CLAUSE_RE = re.compile(r"--no\s+(.+?)\s*$")


def _merge_no_clause(prompt: str, token: str) -> str:
    """Weave the per-job routing needle into the prompt's ``--no`` clause.

    The bridge routes MJ's echoed messages by finding ``cscidnocollide{token}``
    as a substring. If the composed prompt already ends with a user ``--no``
    clause (a negative prompt), append the needle to that one clause — MJ wants
    a single comma-separated ``--no`` list, and a second ``--no`` would break
    its parsing. Otherwise add a fresh trailing ``--no`` clause. Either way the
    needle appears verbatim, so the matchers are unaffected.
    """
    needle = f"cscidnocollide{token}"
    m = _NO_CLAUSE_RE.search(prompt)
    if m:
        return f"{prompt[:m.start()]}--no {m.group(1)}, {needle}"
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
    upscale: str | None = None              # None | "1".."4" | "all"
    status: Status = Status.QUEUED
    progress: str = ""
    message_id: int | None = None           # grid message id
    mj_job_uuid: str | None = None          # extracted from grid buttons
    image_path: str | None = None
    image_url: str | None = None
    grid_path: str | None = None
    grid_url: str | None = None
    upscale_paths: dict[int, str] = field(default_factory=dict)
    upscale_pending: list[int] = field(default_factory=list)
    # Per-slot button-press failures (slot -> error message). During
    # upscale="all", individual U-button presses can fail while others succeed;
    # the job stays in UPSCALING and completes when surviving slots land. If
    # every requested slot's press fails, the job terminates with
    # UPSCALE_ALL_BUTTONS_FAILED. Empty when no presses failed.
    upscale_press_failures: dict[int, str] = field(default_factory=dict)
    error: str | None = None
    error_code: str | None = None
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # "pending" = matched while still in PENDING_GRID; "progress_fallback" =
    # matched after the job was already in PROGRESS (happens when MJ posts the
    # final grid as a new message instead of editing the initial preamble).
    match_path: str | None = None

    def tagged_prompt(self) -> str:
        """Outbound prompt with a per-job token MJ echoes back, used by
        :func:`_match_grid` to route MJ's messages without prefix collisions.
        """
        return _merge_no_clause(self.prompt, self.request_token)

    def touch(self) -> None:
        self.updated_at = time.time()

    def _fail(self, code: str, message: str) -> None:
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


JOBS: OrderedDict[str, Job] = OrderedDict()
PENDING_GRID: list[str] = []  # FIFO of job_ids awaiting grid message match
LOCK = threading.RLock()
TERMINAL_CV = threading.Condition(LOCK)

# Set by the signal/atexit shutdown path. The Discord reconnect loop polls
# this between attempts so the daemon doesn't hammer Discord on the way out.
_shutdown_event = threading.Event()


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


def _evict_if_needed() -> None:
    """Drop terminal jobs older than TTL and evict the oldest terminal job
    when the dict exceeds capacity. Called under LOCK.
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


@client.event
async def on_disconnect():
    """Clear the readiness flag the moment the gateway drops.

    discord.py-self's internal reconnect logic handles transient drops without
    bouncing the process; while it's reconnecting, ``client.ws.session_id``
    may be ``None`` and any interaction call we attempt will 401. Gating
    /imagine on ``_ready.is_set()`` returns a clean 503 DISCORD_NOT_READY
    instead of leaking an AttributeError.
    """
    was_ready = _ready.is_set()
    _ready.clear()
    if was_ready:
        # Only announce drops we actually noticed (suppress the noise of a
        # reconnect attempt that briefly fires on_disconnect before on_ready).
        emit("DISCORD_DISCONNECTED", reason="on_disconnect")


def _session_id_or_raise() -> str:
    """Return ``client.ws.session_id`` or raise :class:`DiscordNotReadyError`.

    Reads the underlying gateway state safely. During a reconnect window the
    websocket is rebuilt and ``client.ws`` can be ``None`` or its session_id
    can be unset; in either case a /imagine or button press would 401, so
    short-circuit with a structured error the Flask layer can return as 503.
    """
    ws = getattr(client, "ws", None)
    if ws is None:
        raise DiscordNotReadyError("client.ws is None (gateway not connected)")
    sid = getattr(ws, "session_id", None)
    if sid is None:
        raise DiscordNotReadyError(
            "client.ws.session_id is None (gateway handshake incomplete)"
        )
    return sid


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


def _job_by_message_id(message_id: int) -> Job | None:
    with LOCK:
        for j in JOBS.values():
            if j.message_id == message_id:
                return j
    return None


def _download_to(url: str, path: Path) -> int:
    """Download ``url`` to ``path``; return the number of bytes written.

    Streams the response body to disk in 64 KB chunks so a large MJ grid
    (typical ~1-3 MB; upscales can reach 8 MB) never sits in memory in full.
    """
    total = 0
    with requests.get(url, timeout=30, stream=True) as resp:
        resp.raise_for_status()
        with path.open("wb") as f:
            for chunk in resp.iter_content(64 * 1024):
                if chunk:
                    total += f.write(chunk)
    return total


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

    job = _job_by_message_id(message.id)
    if job is None:
        job = _match_grid(content)
        if job is not None:
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
            with LOCK:
                job.progress = f"{pct.group(1)}%"
                job.touch()
            return
        if "(Waiting to start)" in content:
            with LOCK:
                job.progress = "queued"
                job.touch()
            return
        if message.attachments:
            # Claim the grid exactly once. on_message and on_message_edit
            # both dispatch _ingest_message via run_in_executor; for the same
            # MJ message both can race here and double-download / double-
            # upscale. Reserve job.grid_path under LOCK before any I/O so a
            # concurrent ingest short-circuits.
            with LOCK:
                if job.grid_path is not None or job.status not in (
                    Status.PROGRESS,
                    Status.SUBMITTED,
                ):
                    return
                job.grid_path = ""  # reservation sentinel — closes the window

            att = message.attachments[0]
            ext = os.path.splitext(att.filename)[1] or ".png"
            suffix = "_grid" if job.upscale else ""
            grid_path = _safe_output_path(
                output_dir=c.output_dir,
                asset_id=job.asset_id,
                suffix=suffix,
                ext=ext,
                request_token=job.request_token,
                kind="grid",
                job_id=job.job_id,
            )
            try:
                grid_bytes = _download_to(att.url, grid_path)
            except Exception as e:
                # Release the reservation so a retry (or the operator's
                # re-fire) doesn't see a permanently-claimed slot.
                with LOCK:
                    if job.grid_path == "":
                        job.grid_path = None
                job._fail("GRID_DOWNLOAD_FAILED", f"grid download failed: {e}")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            with LOCK:
                job.grid_url = att.url
                job.grid_path = str(grid_path)
            emit(
                "GRID_RECEIVED",
                asset_id=job.asset_id,
                job_id=job.job_id,
                path=str(grid_path),
                bytes=grid_bytes,
            )

            if not job.upscale:
                with LOCK:
                    job.image_path = str(grid_path)
                    job.image_url = att.url
                log.info(f"[{job.asset_id}] saved grid -> {grid_path}")
                job._complete()
                return

            mj_uuid = _extract_mj_uuid(message.components)
            if not mj_uuid:
                job._fail(
                    "MJ_UUID_MISSING",
                    "could not find MJ job uuid in grid components",
                )
                log.error(f"[{job.asset_id}] {job.error}")
                return

            slots = [1, 2, 3, 4] if job.upscale == "all" else [int(job.upscale)]
            with LOCK:
                job.mj_job_uuid = mj_uuid
                job.upscale_pending = list(slots)
                job.status = Status.UPSCALING
                job.progress = "upscaling"
                job.touch()
            log.info(
                f"[{job.asset_id}] grid done, requesting upscale "
                f"slots={slots} mj_uuid={mj_uuid[:8]}..."
            )

            guild_id = str(message.guild.id) if message.guild else None
            for n in slots:
                emit(
                    "UPSCALE_REQUESTED",
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    slot=n,
                    mj_job_uuid_prefix=mj_uuid[:8],
                )

            # Fire all button presses concurrently — gather lets a slow Discord
            # interaction on slot 1 not stall slot 2/3/4. return_exceptions=True
            # collects per-slot failures without aborting the others.
            async def _press_all_slots():
                coros = [
                    _press_button(
                        message.id, f"MJ::JOB::upsample::{n}::{mj_uuid}", guild_id
                    )
                    for n in slots
                ]
                return await asyncio.gather(*coros, return_exceptions=True)

            try:
                gather_fut = asyncio.run_coroutine_threadsafe(
                    _press_all_slots(), _running_loop()
                )
                # 35s budget: 30s per-request timeout in _post_interaction +
                # 5s gather/scheduling slack.
                results = gather_fut.result(timeout=35)
            except Exception as e:
                # The gather itself blew up (shouldn't happen with
                # return_exceptions=True except on loop death / timeout).
                job._fail(
                    "UPSCALE_BUTTON_FAILED",
                    f"upscale gather failed: {type(e).__name__}: {e}",
                )
                log.error(f"[{job.asset_id}] {job.error}")
                return

            failed_slots: list[tuple[int, str]] = []
            succeeded_slots: list[int] = []
            for n, result in zip(slots, results, strict=True):
                if isinstance(result, BaseException):
                    code = type(result).__name__
                    msg = str(result) or repr(result)
                    failed_slots.append((n, f"{code}: {msg}"))
                    emit(
                        "UPSCALE_PRESS_FAILED",
                        asset_id=job.asset_id,
                        job_id=job.job_id,
                        slot=n,
                        error_code=code,
                        error_message=msg[:500],
                    )
                elif result.status_code not in (200, 204):
                    code = f"HTTP_{result.status_code}"
                    msg = result.text[:500] if hasattr(result, "text") else ""
                    failed_slots.append((n, f"{code}: {msg[:200]}"))
                    emit(
                        "UPSCALE_PRESS_FAILED",
                        asset_id=job.asset_id,
                        job_id=job.job_id,
                        slot=n,
                        error_code=code,
                        error_message=msg,
                    )
                else:
                    succeeded_slots.append(n)

            with LOCK:
                for n, detail in failed_slots:
                    job.upscale_press_failures[n] = detail
                    if n in job.upscale_pending:
                        job.upscale_pending.remove(n)
                job.touch()

            if not succeeded_slots:
                # Every slot's press failed; the job has nothing to wait for.
                terminal_code = (
                    "UPSCALE_BUTTON_FAILED"
                    if len(slots) == 1
                    else "UPSCALE_ALL_BUTTONS_FAILED"
                )
                detail = "; ".join(f"U{n}: {d}" for n, d in failed_slots)
                job._fail(terminal_code, f"all upscale presses failed — {detail}")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            if failed_slots:
                log.warning(
                    f"[{job.asset_id}] {len(failed_slots)}/{len(slots)} "
                    f"upscale presses failed "
                    f"(U{','.join(str(n) for n, _ in failed_slots)}); "
                    f"continuing to wait for "
                    f"U{','.join(str(n) for n in succeeded_slots)}"
                )
            return

    matched = _match_upscale(content)
    if matched and message.attachments:
        parent, idx = matched
        att = message.attachments[0]
        ext = os.path.splitext(att.filename)[1] or ".png"
        suffix = f"_u{idx}" if parent.upscale == "all" else ""
        out_path = _safe_output_path(
            output_dir=c.output_dir,
            asset_id=parent.asset_id,
            suffix=suffix,
            ext=ext,
            request_token=parent.request_token,
            kind="upscale",
            job_id=parent.job_id,
        )
        try:
            up_bytes = _download_to(att.url, out_path)
        except Exception as e:
            parent._fail(
                "UPSCALE_DOWNLOAD_FAILED",
                f"upscale U{idx} download failed: {e}",
            )
            log.error(f"[{parent.asset_id}] {parent.error}")
            return

        with LOCK:
            parent.upscale_paths[idx] = str(out_path)
            if parent.image_path is None:
                # First upscale to land wins the canonical image slot.
                parent.image_path = str(out_path)
                parent.image_url = att.url
            if idx in parent.upscale_pending:
                parent.upscale_pending.remove(idx)
            parent.touch()
            remaining = list(parent.upscale_pending)

        log.info(f"[{parent.asset_id}] saved upscale U{idx} -> {out_path}")
        emit(
            "UPSCALE_RECEIVED",
            asset_id=parent.asset_id,
            job_id=parent.job_id,
            slot=idx,
            path=str(out_path),
            bytes=up_bytes,
        )
        if not remaining:
            log.info(f"[{parent.asset_id}] all upscales complete")
            parent._complete()


def _running_loop() -> asyncio.AbstractEventLoop:
    """Return the daemon's asyncio loop, raising if it isn't initialized or
    has been closed (would otherwise deadlock).
    """
    loop = _loop_holder["loop"]
    if loop is None or loop.is_closed():
        raise RuntimeError("Discord event loop is not running")
    return loop


@client.event
async def on_message(message):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _ingest_message, message)


@client.event
async def on_message_edit(before, after):
    loop = asyncio.get_running_loop()
    await loop.run_in_executor(None, _ingest_message, after)


async def _post_interaction(payload: dict) -> requests.Response:
    c = _cfg()
    headers = {"Authorization": c.discord_token, "Content-Type": "application/json"}
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: requests.post(
            "https://discord.com/api/v9/interactions",
            json=payload,
            headers=headers,
            timeout=30,
        ),
    )


# Discord Interactions API constants (per
# https://discord.com/developers/docs/interactions/receiving-and-responding).
_INTERACTION_APPLICATION_COMMAND = 2  # slash-command invocation
_INTERACTION_MESSAGE_COMPONENT = 3    # button / select-menu interaction
_COMPONENT_TYPE_BUTTON = 2
_OPTION_TYPE_STRING = 3


async def _send_imagine(prompt: str) -> requests.Response:
    """Fire ``/imagine`` to MJ via the Discord Interactions API.

    Raises :class:`DiscordNotReadyError` if the gateway session_id is not
    available (during reconnect windows). The Flask layer maps this to a
    structured 503 with a retryable error code.
    """
    c = _cfg()
    payload: dict = {
        "type": _INTERACTION_APPLICATION_COMMAND,
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(c.channel_id),
        "session_id": _session_id_or_raise(),
        "data": {
            "version": c.mj_imagine_version,
            "id": c.mj_imagine_command_id,
            "name": "imagine",
            "type": 1,
            "options": [{"type": _OPTION_TYPE_STRING, "name": "prompt", "value": prompt}],
            "application_command": {
                "id": c.mj_imagine_command_id,
                "application_id": str(MJ_BOT_ID),
                "version": c.mj_imagine_version,
                "name": "imagine",
                "type": 1,
                "options": [
                    {"type": _OPTION_TYPE_STRING, "name": "prompt", "description": "The prompt to imagine"}
                ],
            },
        },
    }
    # Required by Discord when the channel lives in a guild — without it the
    # API treats the call as a DM and returns 400 Unknown Channel.
    if c.guild_id:
        payload["guild_id"] = c.guild_id
    return await _post_interaction(payload)


async def _press_button(
    message_id: int, custom_id: str, guild_id: str | None
) -> requests.Response:
    """Press a message component (U1-U4) via the Discord Interactions API.

    Raises :class:`DiscordNotReadyError` if the gateway session_id is not
    available. The button-press caller routes that into a per-slot
    UPSCALE_PRESS_FAILED rather than failing the whole job.
    """
    c = _cfg()
    payload: dict = {
        "type": _INTERACTION_MESSAGE_COMPONENT,
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(c.channel_id),
        "message_id": str(message_id),
        "session_id": _session_id_or_raise(),
        "data": {
            "component_type": _COMPONENT_TYPE_BUTTON,
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
    # JSON booleans get sent as ``true``/``false`` by some HTTP clients; map
    # ``true`` to slot 1 and ``false`` to "no upscale".
    if isinstance(value, bool):
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

    # Submit budget: 35s for the Discord interaction round-trip
    # (_post_interaction uses a 30s requests timeout + scheduling slack).
    # If the call exceeds this, MJ may still have accepted the imagine — the
    # job stays in PENDING_GRID so a late-arriving grid still matches it.
    SUBMIT_TIMEOUT_SECONDS = 35
    fut = asyncio.run_coroutine_threadsafe(
        _send_imagine(job.tagged_prompt()), _running_loop()
    )
    try:
        resp = fut.result(timeout=SUBMIT_TIMEOUT_SECONDS)
    except TimeoutError:
        # Discord didn't return within budget. MJ may or may not have it.
        # Don't fail the job; don't evict from PENDING_GRID. If MJ does
        # process it, the grid-match path will catch the result and resolve
        # /wait normally. If not, /wait's own timeout fires.
        with LOCK:
            job.status = Status.SUBMITTED_UNCONFIRMED
            job.touch()
        emit(
            "JOB_SUBMIT_TIMEOUT",
            asset_id=job.asset_id,
            job_id=job.job_id,
            timeout_seconds=SUBMIT_TIMEOUT_SECONDS,
        )
        log.warning(
            f"[{job.asset_id}] submit interaction timed out after "
            f"{SUBMIT_TIMEOUT_SECONDS}s; job left in PENDING_GRID — "
            f"MJ may still process. Poll /wait/{job.job_id} instead of retrying."
        )
        return jsonify(
            job_id=job.job_id,
            asset_id=job.asset_id,
            status=job.status,
            upscale=upscale,
            note=(
                "Discord interaction timed out before returning. The job is in "
                "PENDING_GRID — MJ may have accepted it. Use /wait or /status "
                "to learn the outcome; do not retry /imagine for this asset "
                "(would bill twice if the original is processed)."
            ),
        ), 202
    except DiscordNotReadyError as e:
        job._fail(e.code, str(e))
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        log.warning(f"[{job.asset_id}] {job.error}")
        return jsonify(
            error=str(e),
            code=e.code,
            remediation=e.remediation,
            job_id=job.job_id,
        ), 503
    except Exception as e:
        job._fail("SUBMIT_FAILED", f"submit failed: {type(e).__name__}: {e}")
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        return jsonify(error=str(e), job_id=job.job_id), 502

    if resp.status_code not in (200, 204):
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

    with LOCK:
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
    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="unknown job_id"), 404
        return jsonify(asdict(job))


@app.get("/wait/<job_id>")
def http_wait(job_id):
    """Block until the job hits done/failed or the timeout fires."""
    timeout_raw = request.args.get("timeout", "120")
    try:
        timeout = float(timeout_raw)
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error={
                "code": "INVALID_TIMEOUT",
                "message": f"timeout must be a number of seconds; got {timeout_raw!r}",
            },
        ), 400
    # Cap so a typo can't park a worker thread for hours.
    timeout = max(0.0, min(timeout, 600.0))
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
    with LOCK:
        discord_ready = _ready.is_set()
        pending = len(PENDING_GRID)
        total = len(JOBS)
        upscaling = sum(1 for j in JOBS.values() if j.status == Status.UPSCALING)
    emit(
        "BRIDGE_HEALTHY",
        discord_ready=discord_ready,
        pending_grid=pending,
        total_jobs=total,
    )
    return jsonify(
        discord_ready=discord_ready,
        pending_grid=pending,
        upscaling=upscaling,
        total_jobs=total,
        output_dir=str(c.output_dir),
    )


def _reconnect_backoff_seconds(attempt: int) -> float:
    """Exponential backoff capped at 60s. ``attempt`` is 1-indexed.

    1 -> 2s, 2 -> 4s, 3 -> 8s, 4 -> 16s, 5 -> 32s, 6+ -> 60s.
    Tests monkeypatch this to short-circuit waits.
    """
    return min(60.0, 2.0 ** min(attempt, 6))


def _is_terminal_auth_failure(exc: BaseException) -> bool:
    """Return True iff an exception from ``client.start`` should stop the
    reconnect loop entirely (no token-rotation hope of recovery).

    discord.py-self surfaces auth failures as :class:`discord.LoginFailure`
    or as :class:`discord.HTTPException` with status 401. Both mean the
    operator must rotate the user token before the daemon can recover, so
    the loop reports DISCORD_RECONNECT_FAILED(auth) and exits rather than
    burning Discord rate limit on guaranteed-401s.
    """
    if isinstance(exc, discord.LoginFailure):
        return True
    return bool(
        isinstance(exc, discord.HTTPException)
        and getattr(exc, "status", None) == 401
    )


def _run_discord() -> None:
    """Run discord.py-self with an outer reconnect loop.

    discord.py-self has internal reconnect for transient WebSocket drops, but
    ``client.start()`` can still return (clean close) or raise (HTTP error,
    network blip past its retry budget, auth failure). When that happens the
    inner loop stops and any subsequent /imagine would 500.

    This wrapper restarts the client with exponential backoff until shutdown
    is signalled or auth fails terminally. Each iteration emits the lifecycle
    tags (DISCORD_DISCONNECTED → DISCORD_RECONNECTING) so an LLM operator
    watching the signal stream sees the daemon's transport state evolve.
    """
    c = _cfg()
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop_holder["loop"] = loop

    attempt = 0
    try:
        while not _shutdown_event.is_set():
            attempt += 1
            try:
                loop.run_until_complete(client.start(c.discord_token))
                # Returned without raising — gateway closed cleanly. _ready
                # may have been cleared by on_disconnect; if not, clear here.
                _ready.clear()
                emit("DISCORD_DISCONNECTED", reason="gateway_close")
            except BaseException as e:
                _ready.clear()
                if _is_terminal_auth_failure(e):
                    log.error(
                        f"Discord auth rejected (terminal): "
                        f"{type(e).__name__}: {e}"
                    )
                    emit(
                        "DISCORD_RECONNECT_FAILED",
                        reason="auth",
                        attempts=attempt,
                    )
                    return
                log.warning(
                    f"Discord client exited unexpectedly "
                    f"(attempt {attempt}): {type(e).__name__}: {e}"
                )
                emit("DISCORD_DISCONNECTED", reason="exception")

            if _shutdown_event.is_set():
                emit(
                    "DISCORD_RECONNECT_FAILED",
                    reason="shutdown",
                    attempts=attempt,
                )
                return

            # Reset client state so the next start() can re-handshake.
            # clear() restores the Client to its initial state; the
            # @client.event registrations live on the class and survive.
            with contextlib.suppress(Exception):
                client.clear()

            backoff = _reconnect_backoff_seconds(attempt)
            emit(
                "DISCORD_RECONNECTING",
                attempt=attempt + 1,
                backoff_seconds=backoff,
            )
            log.info(
                f"Reconnecting to Discord in {backoff:.0f}s "
                f"(attempt {attempt + 1})"
            )
            # Sleep on _shutdown_event so SIGINT/SIGTERM cuts the wait short.
            if _shutdown_event.wait(timeout=backoff):
                emit(
                    "DISCORD_RECONNECT_FAILED",
                    reason="shutdown",
                    attempts=attempt,
                )
                return
    finally:
        # Closed-on-exit so the daemon doesn't leak its event loop or its
        # async resources. The loop holder is cleared so any in-flight
        # /imagine call gets a clean RuntimeError from _running_loop()
        # instead of dispatching onto a dead loop.
        _loop_holder["loop"] = None
        with contextlib.suppress(Exception):
            # Cancel anything still pending on the loop before closing.
            for task in asyncio.all_tasks(loop):
                task.cancel()
        with contextlib.suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())
        with contextlib.suppress(Exception):
            if not loop.is_closed():
                loop.close()


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

    try:
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

    try:
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
    this; whichever runs first wins. Also sets ``_shutdown_event`` so the
    Discord reconnect loop exits without sleeping out its remaining backoff.
    """
    global _shutdown_emitted
    _shutdown_event.set()
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
        raise

    emit("CASCADE_INIT", package_version=PACKAGE_VERSION, backend=BACKEND_NAME)

    t = threading.Thread(target=_run_discord, daemon=True)
    t.start()
    deadline = time.time() + 10.0
    while _loop_holder["loop"] is None:
        if time.time() > deadline:
            raise RuntimeError("Discord event loop failed to initialize within 10s")
        time.sleep(0.05)
    log.info(f"HTTP bridge listening on http://127.0.0.1:{cfg.port}")
    app.run(host="127.0.0.1", port=cfg.port, threaded=True)


if __name__ == "__main__":
    main()

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

import asyncio
import logging
import os
import re
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

import discord  # discord.py-self
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, request

from cascade_img.instrumentation.sdd import emit


PACKAGE_VERSION = "0.0.1"  # bumped in lock-step with pyproject.toml
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
    guild_id: Optional[str]              # required when MJ channel lives in a guild — Sprint 4.0 patch
    mj_imagine_version: str
    mj_imagine_command_id: str
    output_dir: Path
    port: int

    @classmethod
    def from_env(cls) -> "Config":
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
        except ValueError as e:
            raise MissingEnvError(
                "INVALID_PORT",
                f"PORT is not a valid integer: {os.environ.get('PORT')!r}",
                "PORT defaults to 5000. Set a positive integer or leave unset.",
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
cfg: Optional[Config] = None


def _cfg() -> Config:
    """Return the loaded Config, asserting it was set at startup."""
    if cfg is None:
        raise RuntimeError(
            "bridge.cfg is not set — call Config.from_env() and assign to "
            "module-level cfg before starting the daemon."
        )
    return cfg


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
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
    upscale: Optional[str] = None              # None | "1".."4" | "all"
    status: Status = Status.QUEUED
    progress: str = ""
    message_id: Optional[int] = None           # grid message id
    mj_job_uuid: Optional[str] = None          # extracted from grid buttons
    image_path: Optional[str] = None           # canonical output path
    image_url: Optional[str] = None
    grid_path: Optional[str] = None
    grid_url: Optional[str] = None
    upscale_paths: dict = field(default_factory=dict)   # {1: "/path/_u1.png", ...}
    upscale_pending: list = field(default_factory=list) # [1, 2, 3, 4] requested but not yet downloaded
    error: Optional[str] = None
    error_code: Optional[str] = None           # stable code string for JOB_FAILED.error_code
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    # SDD-specific: which path _match_grid took ("pending" first-touch vs
    # "progress_fallback" — the Sprint 4.0 V7 patch path).
    match_path: Optional[str] = None

    def touch(self):
        self.updated_at = time.time()

    def _fail(self, code: str, message: str) -> None:
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

    def _complete(self) -> None:
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


JOBS: dict[str, Job] = {}
PENDING_GRID: list[str] = []  # job_ids awaiting grid message match, FIFO
LOCK = threading.Lock()

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


def _prompt_needle(prompt: str) -> str:
    """The leading non-flag chunk of a prompt, used for substring matching."""
    return prompt.split("--")[0].strip()[:80]


def _match_grid(content: str) -> Optional[Job]:
    """Find oldest pending grid job whose prompt appears in MJ's message.

    Two paths:
    1) Job still in PENDING_GRID — first-touch match (typically MJ's initial
       prompt-echo / "Waiting to start" message). Sets ``job.match_path = "pending"``.
    2) Job already in PROGRESS — modern MJ v7 posts the completed grid as a
       SEPARATE new message (different ID) rather than editing the original.
       Without this fallback the final grid is ignored and the job stalls at
       PROGRESS forever. This is one of the two Sprint-4.0 production patches.
       Sets ``job.match_path = "progress_fallback"`` so the GRID_MATCHED signal
       surfaces which path fired — useful for grading whether the patch was
       exercised.
    """
    with LOCK:
        for job_id in list(PENDING_GRID):
            job = JOBS.get(job_id)
            if not job:
                continue
            needle = _prompt_needle(job.prompt)
            if needle and needle in content and "Image #" not in content:
                PENDING_GRID.remove(job_id)
                job.match_path = "pending"
                return job
        for job in JOBS.values():
            if job.status != Status.PROGRESS:
                continue
            if job.grid_path is not None:
                continue  # already saved; don't re-match
            needle = _prompt_needle(job.prompt)
            if needle and needle in content and "Image #" not in content:
                job.match_path = "progress_fallback"
                return job
    return None


def _match_upscale(content: str) -> Optional[tuple[Job, int]]:
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
            if _prompt_needle(job.prompt) in content:
                return job, idx
    return None


def _job_by_message_id(message_id: int) -> Optional[Job]:
    with LOCK:
        for j in JOBS.values():
            if j.message_id == message_id:
                return j
    return None


def _download_to(url: str, path: Path) -> int:
    data = requests.get(url, timeout=30).content
    path.write_bytes(data)
    return len(data)


def _extract_mj_uuid(components) -> Optional[str]:
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
    _ingest_message(message)


@client.event
async def on_message_edit(before, after):
    _ingest_message(after)


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
    message_id: int, custom_id: str, guild_id: Optional[str]
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


def _normalize_upscale(value) -> Optional[str]:
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

    fut = asyncio.run_coroutine_threadsafe(_send_imagine(prompt), _loop_holder["loop"])
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
    timeout = float(request.args.get("timeout", "120"))
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(error="unknown job_id"), 404
        if job.status in (Status.DONE, Status.FAILED):
            return jsonify(asdict(job))
        time.sleep(2)
    job = JOBS.get(job_id)
    payload = asdict(job) if job else {"error": "unknown job_id"}
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


def main() -> None:
    """Entrypoint for the ``cascade-mj-bridge`` console script."""
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
        # Re-raise so the CLI can surface the structured payload to the
        # operator (LLM or human).
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

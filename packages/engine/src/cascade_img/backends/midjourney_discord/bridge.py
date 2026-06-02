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
  MJ_IMAGINE_VERSION, MJ_IMAGINE_COMMAND_ID. See README.md for the devtools
  capture procedure.

  Then: python mj_bridge.py
"""

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

load_dotenv()

# --- config ---
DISCORD_TOKEN = os.environ["DISCORD_USER_TOKEN"]
CHANNEL_ID = int(os.environ["MJ_CHANNEL_ID"])
GUILD_ID = os.environ.get("MJ_GUILD_ID")  # required when channel is in a guild
MJ_BOT_ID = 936929561302675456
MJ_IMAGINE_VERSION = os.environ["MJ_IMAGINE_VERSION"]
MJ_IMAGINE_COMMAND_ID = os.environ.get(
    "MJ_IMAGINE_COMMAND_ID", "938956540159881230"
)
OUTPUT_DIR = Path(os.environ.get("MJ_OUTPUT_DIR", "./generated")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
PORT = int(os.environ.get("PORT", 5000))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("mj_bridge")


# --- job model ---
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
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def touch(self):
        self.updated_at = time.time()


JOBS: dict[str, Job] = {}
PENDING_GRID: list[str] = []  # job_ids awaiting grid message match, FIFO
LOCK = threading.Lock()

UPSAMPLE_BTN_RE = re.compile(r"MJ::JOB::upsample::(\d+)::([0-9a-f-]+)")
IMAGE_TAG_RE = re.compile(r"Image #(\d+)")
PCT_RE = re.compile(r"\((\d+)%\)")


# --- discord side ---
client = discord.Client()
_loop_holder: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}
_ready = threading.Event()


@client.event
async def on_ready():
    log.info(f"Discord connected as {client.user} (id={client.user.id})")
    log.info(f"Watching channel {CHANNEL_ID}")
    _ready.set()


def _prompt_needle(prompt: str) -> str:
    """The leading non-flag chunk of a prompt, used for substring matching
    against MJ's echoed message content."""
    return prompt.split("--")[0].strip()[:80]


def _match_grid(content: str) -> Optional[Job]:
    """Find oldest pending grid job whose prompt appears in MJ's message.

    Two paths:
    1) Job still in PENDING_GRID — first-touch match (typically MJ's initial
       prompt-echo / "Waiting to start" message).
    2) Job already in PROGRESS — modern MJ v7 posts the completed grid as a
       SEPARATE new message (different ID) rather than editing the original.
       Without this fallback, the final grid is ignored and the job stalls
       at PROGRESS forever.
    """
    with LOCK:
        for job_id in list(PENDING_GRID):
            job = JOBS.get(job_id)
            if not job:
                continue
            needle = _prompt_needle(job.prompt)
            if needle and needle in content and "Image #" not in content:
                PENDING_GRID.remove(job_id)
                return job
        for job in JOBS.values():
            if job.status != Status.PROGRESS:
                continue
            if job.grid_path is not None:
                continue  # already saved; don't re-match
            needle = _prompt_needle(job.prompt)
            if needle and needle in content and "Image #" not in content:
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


def _download_to(url: str, path: Path) -> None:
    data = requests.get(url, timeout=30).content
    path.write_bytes(data)


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
    if message.author.id != MJ_BOT_ID or message.channel.id != CHANNEL_ID:
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
            log.info(f"[{job.asset_id}] matched grid message {message.id}")

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
                    grid_path = OUTPUT_DIR / f"{job.asset_id}_grid{ext}"
                else:
                    grid_path = OUTPUT_DIR / f"{job.asset_id}{ext}"
                _download_to(att.url, grid_path)
                job.grid_path = str(grid_path)
                if not job.upscale:
                    job.image_path = str(grid_path)
                    job.image_url = att.url
                    job.status = Status.DONE
                    job.progress = "100%"
                    job.touch()
                    log.info(f"[{job.asset_id}] saved grid -> {grid_path}")
                    return
            except Exception as e:
                job.status = Status.FAILED
                job.error = f"grid download failed: {e}"
                job.touch()
                log.error(f"[{job.asset_id}] {job.error}")
                return

            # Upscale requested. Extract MJ job uuid, fire button presses.
            job.mj_job_uuid = _extract_mj_uuid(message.components)
            if not job.mj_job_uuid:
                job.status = Status.FAILED
                job.error = "could not find MJ job uuid in grid components"
                job.touch()
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
                out_path = OUTPUT_DIR / f"{parent.asset_id}_u{idx}{ext}"
            else:
                out_path = OUTPUT_DIR / f"{parent.asset_id}{ext}"
            _download_to(att.url, out_path)
            parent.upscale_paths[idx] = str(out_path)
            if parent.image_path is None:
                # First upscale wins canonical slot
                parent.image_path = str(out_path)
                parent.image_url = att.url
            if idx in parent.upscale_pending:
                parent.upscale_pending.remove(idx)
            parent.touch()
            log.info(f"[{parent.asset_id}] saved upscale U{idx} -> {out_path}")
            if not parent.upscale_pending:
                parent.status = Status.DONE
                parent.progress = "100%"
                parent.touch()
                log.info(f"[{parent.asset_id}] all upscales complete")
        except Exception as e:
            parent.status = Status.FAILED
            parent.error = f"upscale U{idx} download failed: {e}"
            parent.touch()
            log.error(f"[{parent.asset_id}] {parent.error}")


@client.event
async def on_message(message):
    _ingest_message(message)


@client.event
async def on_message_edit(before, after):
    _ingest_message(after)


async def _post_interaction(payload: dict) -> requests.Response:
    headers = {"Authorization": DISCORD_TOKEN, "Content-Type": "application/json"}
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
    payload = {
        "type": 2,
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(CHANNEL_ID),
        "session_id": client.ws.session_id,
        "data": {
            "version": MJ_IMAGINE_VERSION,
            "id": MJ_IMAGINE_COMMAND_ID,
            "name": "imagine",
            "type": 1,
            "options": [{"type": 3, "name": "prompt", "value": prompt}],
            "application_command": {
                "id": MJ_IMAGINE_COMMAND_ID,
                "application_id": str(MJ_BOT_ID),
                "version": MJ_IMAGINE_VERSION,
                "name": "imagine",
                "type": 1,
                "options": [
                    {"type": 3, "name": "prompt", "description": "The prompt to imagine"}
                ],
            },
        },
    }
    if GUILD_ID:
        payload["guild_id"] = GUILD_ID
    return await _post_interaction(payload)


async def _press_button(
    message_id: int, custom_id: str, guild_id: Optional[str]
) -> requests.Response:
    payload = {
        "type": 3,  # MESSAGE_COMPONENT
        "application_id": str(MJ_BOT_ID),
        "channel_id": str(CHANNEL_ID),
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


# --- flask side ---
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
        job.status = Status.FAILED
        job.error = f"submit failed: {e}"
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        return jsonify(error=str(e), job_id=job.job_id), 502

    if resp.status_code not in (200, 204):
        job.status = Status.FAILED
        job.error = f"discord {resp.status_code}: {resp.text[:200]}"
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
    return jsonify(
        discord_ready=_ready.is_set(),
        pending_grid=len(PENDING_GRID),
        upscaling=sum(1 for j in JOBS.values() if j.status == Status.UPSCALING),
        total_jobs=len(JOBS),
        output_dir=str(OUTPUT_DIR),
    )


def _run_discord():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    _loop_holder["loop"] = loop
    loop.run_until_complete(client.start(DISCORD_TOKEN))


if __name__ == "__main__":
    t = threading.Thread(target=_run_discord, daemon=True)
    t.start()
    while _loop_holder["loop"] is None:
        time.sleep(0.05)
    log.info(f"HTTP bridge listening on http://127.0.0.1:{PORT}")
    app.run(host="127.0.0.1", port=PORT, threaded=True)

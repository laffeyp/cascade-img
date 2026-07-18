"""The catch-up routes — GET /channel/recent and POST /adopt/<message_id>.

The human is the director and can act in the MJ channel directly (press U4 by
hand, fire a Vary). Those results are invisible to the job matchers — no
tracked job claims them. These two routes close the gap:

* ``/channel/recent`` answers "what happened in the channel?", resolving each
  record against the job table so ``tracked_job_id: null`` means "this happened
  without the bridge".
* ``/adopt/<message_id>`` claims such a result into the job table as a normal
  job (``origin: "adopted"``, already DONE, artifact downloaded to the standard
  path). The adopted message becomes the job's action surface, so ``mj_action``
  and derived-result reply-routing work on it unchanged. Adopting a grid yields
  the artifact only (its U-results route by token + UPSCALING state, which an
  already-done adopted job never enters — retro-U-press is deferred until that
  routing is captured live).

Binding discipline: the loop accessor is read as ``runtime._running_loop`` and
the coroutine dispatch goes through ``_run_on_loop`` (a module-level seam the
test suite monkeypatches); the artifact downloader is called as
``discord_parse._download_to`` per the suite's established patch surface.
"""

from __future__ import annotations

import asyncio
import logging
import os
import uuid as _uuid

import flask
from flask import jsonify, request

from cascade_img.backends.midjourney_discord.config import MJ_BOT_ID, _cfg
from cascade_img.backends.midjourney_discord.errors import DiscordNotReadyError
from cascade_img.backends.midjourney_discord.jobs.job import Job, Status, _evict_if_needed
from cascade_img.backends.midjourney_discord.jobs.job_table import JOBS, LOCK
from cascade_img.backends.midjourney_discord.jobs.persistence import _persist, _safe_output_path
from cascade_img.backends.midjourney_discord.transport import (
    channel_buffer,
    discord_parse,
    runtime,
)
from cascade_img.backends.midjourney_discord.transport.channel_buffer import (
    _IMAGE_TAG_RE,
    message_record,
)
from cascade_img.backends.midjourney_discord.transport.discord_send import _fetch_message
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.routes_catchup")

catchup_bp = flask.Blueprint("catchup", __name__)

# Hard bound on /channel/recent — this is a catch-up window, not a Discord
# browser; the buffer itself holds at most 200.
_RECENT_MAX = 50


def _run_on_loop(coro, timeout: float):
    """Dispatch ``coro`` onto the Discord loop and block for its result. A
    module-level seam so route tests can fake the Discord side without a
    gateway."""
    fut = asyncio.run_coroutine_threadsafe(coro, runtime._running_loop())
    return fut.result(timeout=timeout)


def _job_tracking_message(message_id: int):
    """The job (if any) that already knows this message — as its grid/video
    message, one of its SOLO surfaces, or a derived result it downloaded."""
    with LOCK:
        for j in JOBS.values():
            if j.message_id == message_id or j.upscale_message_id == message_id:
                return j
            if message_id in j.upscale_message_ids.values():
                return j
            if any(d.get("message_id") == message_id for d in j.derived):
                return j
    return None


async def _fetch_recent_history(n: int) -> list:
    """REST-fetch the channel's newest ``n`` messages (cold-buffer fallback,
    e.g. right after a daemon restart). MJ-bot messages only."""
    from cascade_img.backends.midjourney_discord.transport.discord_client import client

    c = _cfg()
    channel = client.get_channel(c.channel_id) or await client.fetch_channel(c.channel_id)
    out = []
    async for m in channel.history(limit=max(n * 2, n + 5)):  # type: ignore[union-attr]
        if m.author.id == MJ_BOT_ID:
            out.append(m)
        if len(out) >= n:
            break
    return out


@catchup_bp.get("/channel/recent")
def http_channel_recent():
    """The newest MJ-bot messages as structured records, newest first.

    Each record carries ``tracked_job_id`` (resolved against the live job
    table; ``null`` = the bridge has no job for it — human-initiated or
    foreign) and ``buttons`` (the ``mj_action`` names present on the message,
    i.e. what adopting it would unlock)."""
    try:
        n = int(request.args.get("n", "10"))
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error={"code": "INVALID_N", "message": "n must be an integer 1-50"},
        ), 400
    n = max(1, min(n, _RECENT_MAX))

    records = channel_buffer.recent_records(n)
    source = "buffer"
    if not records:
        # Cold buffer (fresh daemon). Fall back to one REST history page.
        if not runtime._ready.is_set():
            return jsonify(
                ok=False,
                error={
                    "code": "DISCORD_NOT_READY",
                    "message": "discord client not ready yet, retry in a few seconds",
                    "remediation": DiscordNotReadyError.remediation,
                },
            ), 503
        try:
            messages = _run_on_loop(_fetch_recent_history(n), timeout=35)
        except Exception as e:
            return jsonify(
                ok=False,
                error={
                    "code": "CHANNEL_READ_FAILED",
                    "message": f"history fetch failed: {type(e).__name__}: {e}",
                    "remediation": "Retry after a short delay; a persistent failure "
                    "with 401 needs a token re-capture (RUNBOOK.md).",
                },
            ), 502
        records = [message_record(m) for m in messages]
        source = "history"

    untracked = 0
    for rec in records:
        job = _job_tracking_message(int(rec["message_id"])) if rec["message_id"] else None
        rec["tracked_job_id"] = job.job_id if job else None
        if job is None:
            untracked += 1

    emit("CHANNEL_CATCHUP_READ", n=n, returned=len(records), untracked_count=untracked)
    return jsonify(ok=True, result={"messages": records, "source": source})


@catchup_bp.post("/adopt/<message_id>")
def http_adopt(message_id):
    """Claim an existing MJ channel message into the job table.

    Body: ``{"asset_id": "<name>"}``. The message's artifact downloads to the
    standard output path; the job enters the table DONE with
    ``origin: "adopted"`` and the message registered as its action surface —
    SOLO adoptions unlock ``vary_*``/``zoom_*``/``pan_*``/``animate_*``; video
    adoptions unlock ``video_upscale`` (then ``extend_*``); grid adoptions
    yield the artifact for curation (crop) only."""
    body = request.get_json(silent=True) or {}
    asset_id_raw = body.get("asset_id")
    if not asset_id_raw:
        return jsonify(
            ok=False,
            error={"code": "MISSING_ASSET_ID", "message": "body must carry asset_id"},
        ), 400
    asset_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(asset_id_raw))[:80]

    try:
        mid = int(message_id)
    except (TypeError, ValueError):
        return jsonify(
            ok=False,
            error={"code": "INVALID_MESSAGE_ID", "message": f"not a message id: {message_id!r}"},
        ), 400

    existing = _job_tracking_message(mid)
    if existing is not None:
        return jsonify(
            ok=False,
            error={
                "code": "ALREADY_TRACKED",
                "message": f"message {mid} already belongs to job {existing.job_id}",
                "remediation": "Act on the existing job_id instead of adopting again.",
                "job_id": existing.job_id,
            },
        ), 409

    if not runtime._ready.is_set():
        return jsonify(
            ok=False,
            error={
                "code": "DISCORD_NOT_READY",
                "message": "discord client not ready yet, retry in a few seconds",
                "remediation": DiscordNotReadyError.remediation,
            },
        ), 503

    try:
        message = _run_on_loop(_fetch_message(mid), timeout=35)
    except Exception as e:
        not_found = "NotFound" in type(e).__name__ or "Unknown Message" in str(e)
        return jsonify(
            ok=False,
            error={
                "code": "MESSAGE_NOT_FOUND" if not_found else "CHANNEL_READ_FAILED",
                "message": f"message fetch failed: {type(e).__name__}: {e}",
                "remediation": "Check /channel/recent for the right message id.",
            },
        ), 404 if not_found else 502

    if getattr(getattr(message, "author", None), "id", None) != MJ_BOT_ID:
        return jsonify(
            ok=False,
            error={
                "code": "NOT_AN_MJ_MESSAGE",
                "message": "only Midjourney-bot messages are adoptable",
            },
        ), 400

    rec = message_record(message)
    kind = rec["kind"]
    if kind == "other" or not rec["attachment"]:
        return jsonify(
            ok=False,
            error={
                "code": "NOT_AN_MJ_MESSAGE",
                "message": "message carries no adoptable artifact (no attachment)",
            },
        ), 400

    c = _cfg()
    att = message.attachments[0]
    ext = os.path.splitext(getattr(att, "filename", "") or "")[1] or ".png"
    job_id = _uuid.uuid4().hex
    out_path = _safe_output_path(
        output_dir=c.output_dir,
        asset_id=asset_id,
        suffix="",
        ext=ext,
        request_token="adopted",
        kind="adopted",
        job_id=job_id,
    )
    try:
        nbytes = discord_parse._download_to(att.url, out_path)
    except Exception as e:
        return jsonify(
            ok=False,
            error={
                "code": "ADOPT_DOWNLOAD_FAILED",
                "message": f"artifact download failed: {type(e).__name__}: {e}",
                "remediation": "Retry the adopt.",
            },
        ), 502

    token_m = rec["routing_token"]
    job = Job(
        job_id=job_id,
        asset_id=asset_id,
        prompt=rec["prompt_text"],
        origin="adopted",
        kind="video" if kind == "video" else "image",
        status=Status.DONE,
        progress="100%",
        image_path=str(out_path),
        image_url=att.url,
    )
    if kind == "solo":
        # The SOLO message is the vary/zoom/pan/animate action surface, and
        # derived results reply to it (routed by _job_by_upscale_message_id).
        job.upscale_message_id = mid
        slot_m = _IMAGE_TAG_RE.search(rec["prompt_text"])
        slot = int(slot_m.group(1)) if slot_m else 1
        job.upscale_message_ids[slot] = mid
        job.upscale_paths[slot] = str(out_path)
    elif kind == "video":
        # video_upscale presses target message_id; a DONE video job's replies
        # route via _video_result_parent.
        job.message_id = mid
        job.grid_path = str(out_path)
    else:  # grid
        job.message_id = mid
        job.grid_path = str(out_path)

    with LOCK:
        JOBS[job.job_id] = job
        _persist(job)
        _evict_if_needed()

    emit(
        "MESSAGE_ADOPTED",
        message_id=mid,
        asset_id=asset_id,
        job_id=job.job_id,
        kind=kind,
        had_routing_token=bool(token_m),
        bytes=nbytes,
    )
    log.info(f"[{asset_id}] adopted message {mid} as job {job.job_id} (kind={kind})")
    return jsonify(
        ok=True,
        result={
            "job_id": job.job_id,
            "asset_id": asset_id,
            "kind": kind,
            "image_path": str(out_path),
            "buttons": rec["buttons"],
            "origin": "adopted",
        },
    )

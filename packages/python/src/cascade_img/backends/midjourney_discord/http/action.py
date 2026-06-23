"""The action route — POST /action/<job_id> — as a Flask Blueprint.

Registered onto ``app`` in app.py. The nested ``_do()`` coroutine closes over
``message_id`` / ``slot`` / ``action``.

Binding discipline: the loop accessor is read as ``runtime._running_loop`` (the
suite patches it on ``runtime``); ``asyncio.run_coroutine_threadsafe`` is the
module global the suite patches process-wide.
"""

from __future__ import annotations

import asyncio
import logging

import flask
from flask import jsonify, request

from cascade_img.backends.midjourney_discord.config import _cfg
from cascade_img.backends.midjourney_discord.errors import DiscordNotReadyError
from cascade_img.backends.midjourney_discord.jobs.job_table import JOBS, LOCK
from cascade_img.backends.midjourney_discord.transport import runtime
from cascade_img.backends.midjourney_discord.transport.discord_parse import (
    _ACTION_MARKERS,
    _find_action_custom_id,
)
from cascade_img.backends.midjourney_discord.transport.discord_send import (
    _fetch_message,
    _press_button,
)
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.routes_action")

action_bp = flask.Blueprint("action", __name__)


@action_bp.post("/action/<job_id>")
def http_action(job_id):
    """Press a response-message button on a completed job's upscaled image.

    The buttons MJ attaches to a SOLO upscaled image — upscale subtle/creative,
    vary subtle/strong, zoom-out, pan, animate high/low, favorite — are driven
    here without a human clicking. The bridge fetches the live message, reads
    the button's current ``custom_id`` (never hardcoded), and presses it.

    Body: ``{"action": "<name>", "slot": <1-4, optional>}`` where name is one of
    ``_ACTION_MARKERS``. ``slot`` targets a specific SOLO image under
    ``upscale="all"`` (four actionable surfaces); omit it to use the canonical
    one (the slot that produced ``image_path``). Returns the
    ``{ok, result | error}`` envelope. The pressed action's derived result (a new
    grid for vary/zoom/pan, a video for animate) is routed back to this job and
    recorded in ``Job.derived``.
    """
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    if action not in _ACTION_MARKERS:
        return jsonify(
            ok=False,
            error={
                "code": "UNKNOWN_ACTION",
                "message": f"action must be one of {sorted(_ACTION_MARKERS)}; got {action!r}",
                "remediation": "Pass a supported action name. See RUNBOOK.md.",
            },
        ), 400

    slot = body.get("slot")
    if slot is not None:
        try:
            slot = int(slot)
        except TypeError, ValueError:
            return jsonify(
                ok=False,
                error={
                    "code": "INVALID_SLOT",
                    "message": f"slot must be an integer 1-4 (or omitted); got {slot!r}",
                },
            ), 400

    if not runtime._ready.is_set():
        return jsonify(
            ok=False,
            error={
                "code": "DISCORD_NOT_READY",
                "message": "discord client not ready yet, retry in a few seconds",
                "remediation": DiscordNotReadyError.remediation,
            },
        ), 503

    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify(
                ok=False,
                error={"code": "UNKNOWN_JOB", "message": "unknown job_id"},
            ), 404
        if job.kind == "video":
            # video_upscale lives on the video grid message; extend_high/low live
            # on a per-slot SOLO clip, recorded as a surface in upscale_message_ids
            # when that SOLO lands (MJ_ACTION_SURFACE_REGISTERED).
            if action in ("extend_high", "extend_low"):
                message_id = job.upscale_message_ids.get(slot or 1)
            else:
                message_id = job.message_id
        else:
            message_id = (
                job.upscale_message_ids.get(slot) if slot is not None else job.upscale_message_id
            )
        asset_id = job.asset_id

    if message_id is None:
        if job.kind == "video" and action in ("extend_high", "extend_low"):
            detail = (
                f"no SOLO video for slot {slot or 1}; recorded extend surfaces: "
                f"{sorted(job.upscale_message_ids)}"
            )
            remediation = (
                "Press video_upscale on that slot first (mj_action 'video_upscale', "
                "slot=N) to extract the SOLO clip the extend buttons live on, then retry."
            )
        elif job.kind == "video":
            detail = "the video grid result is not available yet (job not done)"
            remediation = (
                "Wait for the video job to finish (status == 'done') before pressing "
                "its result buttons."
            )
        else:
            detail = (
                f"no upscaled image for slot {slot}; available slots: {sorted(job.upscale_message_ids)}"
                if slot is not None
                else "job has no upscaled image; these buttons live on a SOLO upscale"
            )
            remediation = "Run the job with upscale=1-4 (or 'all'), then retry the action."
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code="NO_UPSCALED_IMAGE",
            error_message=detail,
        )
        return jsonify(
            ok=False,
            error={
                "code": "NO_UPSCALED_IMAGE",
                "message": detail,
                "remediation": remediation,
            },
        ), 409

    async def _do():
        message = await _fetch_message(message_id)
        custom_id = _find_action_custom_id(message, action, slot=slot)
        if custom_id is None:
            return None, None
        guild_id = str(message.guild.id) if message.guild else _cfg().guild_id
        resp = await _press_button(message_id, custom_id, guild_id)
        return custom_id, resp

    try:
        fut = asyncio.run_coroutine_threadsafe(_do(), runtime._running_loop())
        # 35s budget: a REST message-fetch plus the interaction round-trip
        # (_post_interaction's 30s requests timeout + slack).
        custom_id, resp = fut.result(timeout=35)
    except DiscordNotReadyError as e:
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code="DISCORD_NOT_READY",
            error_message=str(e),
        )
        return jsonify(
            ok=False,
            error={"code": "DISCORD_NOT_READY", "message": str(e), "remediation": e.remediation},
        ), 503
    except TimeoutError:
        # concurrent.futures.TimeoutError is an alias of the builtin TimeoutError
        # on 3.14, so catching the builtin covers the run_coroutine_threadsafe
        # timeout — it won't fall through to the generic handler with an opaque,
        # undeclared error code.
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code="ACTION_TIMEOUT",
            error_message="action timed out after 35s",
        )
        return jsonify(
            ok=False,
            error={
                "code": "ACTION_TIMEOUT",
                "message": "Discord action timed out after 35s; the press may or may not have landed.",
                "remediation": "Poll the job's status; do not blindly retry the same action.",
            },
        ), 504
    except Exception as e:
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code=type(e).__name__,
            error_message=str(e)[:300],
        )
        return jsonify(
            ok=False,
            error={"code": type(e).__name__, "message": str(e)},
        ), 502

    if custom_id is None:
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code="BUTTON_NOT_FOUND",
            error_message=f"no {action} button on message {message_id}",
        )
        return jsonify(
            ok=False,
            error={
                "code": "BUTTON_NOT_FOUND",
                "message": f"no {action!r} button found on the upscaled image",
                "remediation": "MJ may not offer this action for this image/version.",
            },
        ), 404

    if resp.status_code not in (200, 204):
        emit(
            "MJ_ACTION_FAILED",
            job_id=job_id,
            action=action,
            error_code=f"HTTP_{resp.status_code}",
            error_message=resp.text[:300],
        )
        return jsonify(
            ok=False,
            error={"code": f"HTTP_{resp.status_code}", "message": resp.text[:300]},
        ), 502

    emit(
        "MJ_ACTION_REQUESTED",
        job_id=job_id,
        action=action,
        custom_id=custom_id,
        message_id=message_id,
    )
    log.info(f"[{asset_id}] pressed {action} on message {message_id}")
    return jsonify(
        ok=True,
        result={
            "job_id": job_id,
            "action": action,
            "custom_id": custom_id,
            "message_id": message_id,
        },
    )

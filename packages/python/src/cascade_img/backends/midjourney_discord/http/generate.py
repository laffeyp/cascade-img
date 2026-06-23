"""The generation routes — POST /imagine and POST /video — as a Flask Blueprint.

Registered onto ``app`` in app.py.

Binding discipline: readiness and the loop accessor are read as ``runtime._ready``
/ ``runtime._running_loop`` so the suite's patches (retargeted to ``runtime``)
reach them; ``asyncio.run_coroutine_threadsafe`` is the module global the suite
patches process-wide.
"""

from __future__ import annotations

import asyncio
import logging
import uuid

import flask
from flask import jsonify, request

from cascade_img.backends.midjourney_discord.errors import DiscordNotReadyError
from cascade_img.backends.midjourney_discord.http.app import _normalize_upscale
from cascade_img.backends.midjourney_discord.ingest.matching import _find_job_by_idempotency_key
from cascade_img.backends.midjourney_discord.jobs.job import Job, Status, _evict_if_needed
from cascade_img.backends.midjourney_discord.jobs.job_table import (
    JOBS,
    LOCK,
    PENDING_GRID,
    PENDING_VIDEO,
)
from cascade_img.backends.midjourney_discord.jobs.persistence import _persist
from cascade_img.backends.midjourney_discord.transport import runtime
from cascade_img.backends.midjourney_discord.transport.discord_send import _send_imagine
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.routes_generate")

generate_bp = flask.Blueprint("generate", __name__)


@generate_bp.post("/imagine")
def http_imagine():
    if not runtime._ready.is_set():
        return jsonify(
            error="discord client not ready yet, retry in a few seconds",
            code="DISCORD_NOT_READY",
        ), 503

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify(error="missing 'prompt'"), 400

    try:
        upscale = _normalize_upscale(body.get("upscale"))
    except ValueError as e:
        return jsonify(error=str(e)), 400

    asset_id_raw = body.get("asset_id") or f"asset_{uuid.uuid4().hex[:8]}"
    asset_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(asset_id_raw))[:80]

    idem_raw = body.get("idempotency_key")
    idempotency_key = str(idem_raw)[:200] if idem_raw else None

    with LOCK:
        # Idempotent replay: a caller firing the same key again (e.g. retrying a
        # cancelled-mid-imagine MCP call whose orphaned POST already landed) gets
        # the existing job back instead of a second submission/bill. Checked and
        # the job inserted atomically under LOCK so two racing identical-key
        # POSTs can't both create a job.
        if idempotency_key:
            existing = _find_job_by_idempotency_key(idempotency_key)
            if existing is not None:
                log.info(
                    f"[{existing.asset_id}] idempotent replay of {existing.job_id} "
                    f"(key={idempotency_key[:16]}…); not re-submitting"
                )
                return jsonify(
                    job_id=existing.job_id,
                    asset_id=existing.asset_id,
                    status=existing.status,
                    upscale=existing.upscale,
                    idempotent_replay=True,
                )
        job = Job(
            job_id=uuid.uuid4().hex,
            asset_id=asset_id,
            prompt=prompt,
            upscale=upscale,
            idempotency_key=idempotency_key,
        )
        JOBS[job.job_id] = job
        _persist(job)
        PENDING_GRID.append(job.job_id)
        _evict_if_needed()

    # Submit budget: 35s for the Discord interaction round-trip
    # (_post_interaction uses a 30s requests timeout + scheduling slack).
    # If the call exceeds this, MJ may still have accepted the imagine — the
    # job stays in PENDING_GRID so a late-arriving grid still matches it.
    SUBMIT_TIMEOUT_SECONDS = 35
    fut = asyncio.run_coroutine_threadsafe(
        _send_imagine(job.tagged_prompt()), runtime._running_loop()
    )
    try:
        resp = fut.result(timeout=SUBMIT_TIMEOUT_SECONDS)
    except TimeoutError:
        # ``run_coroutine_threadsafe`` returns a concurrent.futures.Future whose
        # ``.result()`` raises concurrent.futures.TimeoutError — an alias of the
        # builtin ``TimeoutError`` on the project's 3.14 target, so catching the
        # builtin alone covers it.
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
            # Any other non-2xx: a single bounded code (the status lives in the
            # message) so error_code stays inside the locked JOB_FAILED enum.
            code = "DISCORD_HTTP_ERROR"
        job._fail(code, f"discord {resp.status_code}: {text}")
        with LOCK:
            if job.job_id in PENDING_GRID:
                PENDING_GRID.remove(job.job_id)
        log.error(f"[{job.asset_id}] {job.error}")
        return jsonify(error=job.error, job_id=job.job_id), 502

    with LOCK:
        job.status = Status.SUBMITTED
        job.touch()
    log.info(f"[{job.asset_id}] submitted: upscale={upscale or '-'} prompt={prompt[:80]}")
    emit(
        "IMAGINE_FIRED",
        asset_id=job.asset_id,
        job_id=job.job_id,
        prompt_chars=len(prompt),
        upscale=upscale,
    )
    return jsonify(job_id=job.job_id, asset_id=job.asset_id, status=job.status, upscale=upscale)


@generate_bp.post("/video")
def http_video():
    """Fire a NATIVE video generation: ``<image_url> [text] --video [params]``.

    Distinct from /imagine in three ways: the prompt is fired RAW (video prompts
    reject the ``--no`` routing token, so there's nothing to merge); the job is
    kind="video" and waits in PENDING_VIDEO to be bound to MJ's echoed
    ``s.mj.run/XXX`` short URL (F34); and it emits VIDEO_REQUESTED. The final
    artifact is one animated webp, downloaded through the same lifecycle as a
    grid (it has no upscale). Caller supplies the already-composed video
    ``prompt`` (the MCP/backend layer builds it via PromptComposer.compose_video).
    """
    if not runtime._ready.is_set():
        return jsonify(
            error="discord client not ready yet, retry in a few seconds",
            code="DISCORD_NOT_READY",
        ), 503

    body = request.get_json(silent=True) or {}
    prompt = (body.get("prompt") or "").strip()
    if not prompt:
        return jsonify(error="missing 'prompt'"), 400
    if "--video" not in prompt:
        return jsonify(
            error="a /video prompt must contain --video (compose with compose_video)",
            code="NOT_A_VIDEO_PROMPT",
        ), 400

    asset_id_raw = body.get("asset_id") or f"asset_{uuid.uuid4().hex[:8]}"
    asset_id = "".join(c if c.isalnum() or c in "._-" else "_" for c in str(asset_id_raw))[:80]

    with LOCK:
        # Serialize video submission: a video can't carry the --no routing token,
        # so it's bound to MJ's echoed short URL on a FIFO basis. Allowing two
        # videos to await their first ack at once would make that bind ambiguous
        # (out-of-order acks could swap them), so refuse while one is unbound.
        # The window is brief — a job leaves PENDING_VIDEO as soon as it binds —
        # so a still-rendering video does NOT block the next submit. (review R1)
        if PENDING_VIDEO:
            return jsonify(
                error=(
                    "a video is already awaiting its first Midjourney ack; submit "
                    "videos serially (one unbound at a time) so result routing "
                    "stays unambiguous — poll /wait then submit the next"
                ),
                code="VIDEO_IN_FLIGHT",
            ), 409
        job = Job(job_id=uuid.uuid4().hex, asset_id=asset_id, prompt=prompt, kind="video")
        JOBS[job.job_id] = job
        _persist(job)
        PENDING_VIDEO.append(job.job_id)
        _evict_if_needed()

    SUBMIT_TIMEOUT_SECONDS = 35
    # Fire the RAW prompt — no tagged_prompt() (video rejects --no).
    fut = asyncio.run_coroutine_threadsafe(_send_imagine(job.prompt), runtime._running_loop())
    try:
        resp = fut.result(timeout=SUBMIT_TIMEOUT_SECONDS)
    except TimeoutError:
        with LOCK:
            job.status = Status.SUBMITTED_UNCONFIRMED
            job.touch()
        emit(
            "JOB_SUBMIT_TIMEOUT",
            asset_id=job.asset_id,
            job_id=job.job_id,
            timeout_seconds=SUBMIT_TIMEOUT_SECONDS,
        )
        return jsonify(
            job_id=job.job_id,
            asset_id=job.asset_id,
            status=job.status,
            note=(
                "Discord interaction timed out before returning. The video job is "
                "in PENDING_VIDEO — MJ may have accepted it. Use /wait or /status; "
                "do not retry (would bill twice)."
            ),
        ), 202
    except DiscordNotReadyError as e:
        job._fail(e.code, str(e))
        with LOCK:
            if job.job_id in PENDING_VIDEO:
                PENDING_VIDEO.remove(job.job_id)
        return jsonify(error=str(e), code=e.code, remediation=e.remediation, job_id=job.job_id), 503
    except Exception as e:
        job._fail("VIDEO_SUBMIT_FAILED", f"submit failed: {type(e).__name__}: {e}")
        with LOCK:
            if job.job_id in PENDING_VIDEO:
                PENDING_VIDEO.remove(job.job_id)
        return jsonify(error=str(e), job_id=job.job_id), 502

    if resp.status_code not in (200, 204):
        text = resp.text[:200]
        code = "DISCORD_401" if resp.status_code == 401 else "VIDEO_SUBMIT_FAILED"
        job._fail(code, f"discord {resp.status_code}: {text}")
        with LOCK:
            if job.job_id in PENDING_VIDEO:
                PENDING_VIDEO.remove(job.job_id)
        log.error(f"[{job.asset_id}] {job.error}")
        return jsonify(error=job.error, job_id=job.job_id), 502

    with LOCK:
        job.status = Status.SUBMITTED
        job.touch()
    log.info(f"[{job.asset_id}] video submitted: prompt={prompt[:80]}")
    emit("VIDEO_REQUESTED", asset_id=job.asset_id, job_id=job.job_id, prompt_chars=len(prompt))
    return jsonify(job_id=job.job_id, asset_id=job.asset_id, status=job.status)

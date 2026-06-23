"""The Flask app, the query/health routes, and blueprint registration.

``app`` lives here; the generation routes (/imagine, /video) and the action
route (/action) live in their own Blueprint modules and are registered onto
``app`` at the bottom of this file.

Binding discipline: readiness is read as ``runtime._ready`` (a shared Event, also
re-exported as ``bridge._ready``); the durable-store accessor and matchers come
from their owning modules.
"""

from __future__ import annotations

import logging
import time
from dataclasses import asdict

from flask import Flask, jsonify, request

from cascade_img.backends.midjourney_discord.config import _cfg
from cascade_img.backends.midjourney_discord.jobs.job import Status
from cascade_img.backends.midjourney_discord.jobs.job_table import (
    JOBS,
    LOCK,
    PENDING_GRID,
    TERMINAL_CV,
)
from cascade_img.backends.midjourney_discord.transport import runtime
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.routes")

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
    except TypeError, ValueError:
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
        discord_ready = runtime._ready.is_set()
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


# Register the generation (/imagine, /video) and action (/action) Blueprints onto
# ``app``. Imported at the bottom so the route modules can import ``app``-free
# helpers from here (``_normalize_upscale``) without a circular import.
from cascade_img.backends.midjourney_discord.http.action import (  # noqa: E402
    action_bp,
)
from cascade_img.backends.midjourney_discord.http.generate import (  # noqa: E402
    generate_bp,
)

app.register_blueprint(generate_bp)
app.register_blueprint(action_bp)

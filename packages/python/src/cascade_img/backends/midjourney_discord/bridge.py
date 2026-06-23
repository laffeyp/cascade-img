"""Midjourney bridge daemon.

A Flask service that drives Midjourney from a Discord user account.

    POST /imagine {prompt, asset_id, upscale?} -> {job_id}
    POST /action/<job_id> {action, slot?}          -> presses a result button (vary/zoom/pan/upscale/animate)
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
import atexit
import contextlib
import logging
import os
import signal
import threading
import time

# bridge.py is the assembly module: it re-imports the names that live in the
# focused submodules so ``bridge.<name>`` references (and the test suite's
# monkeypatches that target them) resolve here unchanged.
#
# cfg is reassigned at startup via ``config.cfg = ...`` in main(); read it only
# through the ``_cfg()`` accessor, never by importing the ``cfg`` value. Likewise
# the durable ``_store`` is read as ``persistence._store`` (reassigned at
# startup), never imported by value.
from cascade_img.backends.midjourney_discord import config
from cascade_img.backends.midjourney_discord.config import (
    BACKEND_NAME,
    INFLIGHT_TIMEOUT_SECONDS,
    PACKAGE_VERSION,
    Config,
)
from cascade_img.backends.midjourney_discord.diagnostics import check_env, doctor
from cascade_img.backends.midjourney_discord.errors import (
    MissingEnvError,
)
from cascade_img.backends.midjourney_discord.http.app import app
from cascade_img.backends.midjourney_discord.jobs import persistence
from cascade_img.backends.midjourney_discord.jobs.job_store import JobStore
from cascade_img.backends.midjourney_discord.jobs.maintenance import _reaper_loop
from cascade_img.backends.midjourney_discord.jobs.rehydrate import _rehydrate_jobs
from cascade_img.backends.midjourney_discord.transport.discord_client import (
    _run_discord,
)
from cascade_img.backends.midjourney_discord.transport.runtime import (
    _loop_holder,
    _shutdown_event,
)
from cascade_img.vocabulary import emit

# Module-level logger only. ``logging.basicConfig`` is NOT called here — that
# would clobber configuration done by embedding callers (a host that imports
# this module to drive the bridge in-process should own its logging config).
# The ``cascade-mj-bridge`` CLI's ``main()`` calls basicConfig when it owns
# the process; everywhere else, the logger inherits the consumer's config.
log = logging.getLogger("cascade_img.bridge")


# ---------------------------------------------------------------------------
# bridge.py is the slim assembly module: the ``cascade-mj-bridge`` console
# entrypoint (main()), the shutdown plumbing, and the startup wiring that bolts
# the focused modules together. Every other concern lives in its own module
# (re-imported above so ``bridge.<name>`` still resolves for callers and tests):
#   job model / table    -> jobs/job.py, jobs/job_table.py
#   Discord client       -> transport/discord_client.py
#   inbound ingestion    -> ingest/messages.py, ingest/derived.py
#   HTTP routes + app    -> http/app.py, http/generate.py, http/action.py
#   --check-env/--doctor -> diagnostics.py
# ---------------------------------------------------------------------------


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
    except ValueError, OSError:
        # Non-main-thread or platform without signal support — atexit catches it.
        pass

    parser = argparse.ArgumentParser(prog="cascade-mj-bridge")
    grp = parser.add_mutually_exclusive_group()
    grp.add_argument(
        "--check-env", action="store_true", help="Validate config and exit. JSON to stdout."
    )
    grp.add_argument(
        "--doctor",
        action="store_true",
        help="Full pre-flight check (env + reachability + imports). JSON to stdout.",
    )
    parser.add_argument(
        "--pretty", action="store_true", help="Indent JSON output (--check-env / --doctor only)."
    )
    args = parser.parse_args()

    if args.check_env:
        result = check_env()
        print(_json.dumps(result, indent=2 if args.pretty else None))
        sys.exit(0 if result["ok"] else 1)

    if args.doctor:
        result = doctor()
        print(_json.dumps(result, indent=2 if args.pretty else None))
        sys.exit(0 if result["ok"] else 1)

    # Default: run the daemon. cfg lives in config.py; publish it by module
    # attribute so the config._cfg() accessor (and every reader) sees it.
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
    config.cfg = cfg

    emit("CASCADE_INIT", package_version=PACKAGE_VERSION, backend=BACKEND_NAME)

    db_path = os.environ.get("CASCADE_JOB_DB") or str(cfg.output_dir / "cascade-jobs.db")
    persistence._store = JobStore(db_path)
    emit("JOB_STORE_INITIALIZED", path=db_path, mode=persistence._store.mode)
    # Rehydration is a best-effort resume convenience, never a startup gate: a
    # bad store must not stop the daemon from coming up and serving new jobs.
    try:
        rehydrated = _rehydrate_jobs()
    except Exception as e:
        log.warning(
            f"job rehydration failed ({type(e).__name__}: {e}); starting with an empty job map"
        )
        rehydrated = 0
    emit("JOB_STORE_REHYDRATED", count=rehydrated)
    if rehydrated:
        log.info(f"rehydrated {rehydrated} in-flight job(s) from {db_path}")

    # Stalled-job reaper: fails in-flight jobs gone silent past
    # INFLIGHT_TIMEOUT_SECONDS so a stuck PROGRESS / UPSCALING / unconfirmed job
    # becomes terminal (and evictable) instead of a permanent phantom row. Sweep
    # at most once a minute; the timeout itself is what's generous.
    reap_interval = max(5.0, min(INFLIGHT_TIMEOUT_SECONDS, 60.0))
    threading.Thread(
        target=_reaper_loop, args=(reap_interval,), name="job-reaper", daemon=True
    ).start()

    t = threading.Thread(target=_run_discord, daemon=True)
    t.start()
    deadline = time.time() + 10.0
    while _loop_holder["loop"] is None:
        if time.time() > deadline:
            raise RuntimeError("Discord event loop failed to initialize within 10s")
        time.sleep(0.05)

    # Serve via an explicit make_server in a daemon thread and block the main
    # thread on _shutdown_event, instead of app.run() (which does not reliably
    # unblock on the signal handler's SystemExit — the dev server could linger
    # bound to the port, needing a second signal). On shutdown we call
    # srv.shutdown() from the MAIN thread (never the serve thread, which would
    # deadlock), closing the listening socket cleanly on the first SIGINT/SIGTERM.
    from werkzeug.serving import make_server

    srv = make_server("127.0.0.1", cfg.port, app, threaded=True)
    server_thread = threading.Thread(target=srv.serve_forever, name="flask-serve", daemon=True)
    server_thread.start()
    log.info(f"HTTP bridge listening on http://127.0.0.1:{cfg.port}")
    try:
        # _shutdown_event is set by the signal handler / atexit; the 1s re-check
        # is belt-and-suspenders in case a signal doesn't interrupt the wait.
        while not _shutdown_event.wait(timeout=1.0):
            pass
    finally:
        with contextlib.suppress(Exception):
            srv.shutdown()


if __name__ == "__main__":
    main()

"""Event-loop and thread-pool substrate shared by ingest and the Discord client.

Extracted from bridge.py (sprint 023.4). This module exists to break the
``discord_client -> ingest -> (loop/pools) -> client`` cycle: both the Discord
client and message ingestion import the loop/pool holders from here, neither
from each other.

Binding discipline: the holders (``_loop_holder``, ``_POOLS``) are dicts mutated
in place, and ``_ready``/``_shutdown_event`` are ``Event`` objects never rebound,
so importing them by name elsewhere is safe. ``_running_loop()`` reads
``_loop_holder["loop"]`` and stays co-located with the holder.
"""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

# Set by the signal/atexit shutdown path. The Discord reconnect loop polls
# this between attempts so the daemon doesn't hammer Discord on the way out.
_shutdown_event = threading.Event()

_loop_holder: dict[str, asyncio.AbstractEventLoop | None] = {"loop": None}
_ready = threading.Event()

# Dedicated executors, created in _run_discord. Message ingestion blocks on real
# I/O (the grid/upscale/derived downloads) and, in the upscale path, waits up to
# 35s on the button presses it scheduled. If ingestion and those presses shared
# the loop's single default executor, ingest threads could occupy every worker
# while blocked waiting for presses that can't get a worker — a pool-exhaustion
# deadlock — and long downloads would starve progress-edit ingestion. So ingest
# and outbound HTTP get separate pools. None until _run_discord sets them; a
# None value means run_in_executor falls back to the loop default (the path
# unit tests that call _ingest_message directly take).
_POOLS: dict[str, ThreadPoolExecutor | None] = {"ingest": None, "http": None}


def _running_loop() -> asyncio.AbstractEventLoop:
    """Return the daemon's asyncio loop, raising if it isn't initialized or
    has been closed (would otherwise deadlock).
    """
    loop = _loop_holder["loop"]
    if loop is None or loop.is_closed():
        raise RuntimeError("Discord event loop is not running")
    return loop

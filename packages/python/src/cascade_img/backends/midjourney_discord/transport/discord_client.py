"""The live Discord client object and gateway-session accessor.

Holds the ``client`` singleton, ``_session_id_or_raise`` (which the outbound
senders need), the gateway event handlers, the reconnect loop, and the
auth/backoff helpers.

Binding discipline: ``client`` is a singleton mutated/replaced by discord.py-self
internals but never rebound by us at module level, so importing it by name is
safe; the test suite patches ``discord_client.client.ws`` / ``.start`` on this
object. ``_session_id_or_raise`` reads ``client`` from this module so those
patches reach it.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from concurrent.futures import ThreadPoolExecutor

import discord

from cascade_img.backends.midjourney_discord.config import _cfg
from cascade_img.backends.midjourney_discord.errors import DiscordNotReadyError
from cascade_img.backends.midjourney_discord.transport import runtime
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.discord_client")

client = discord.Client()


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
        raise DiscordNotReadyError("client.ws.session_id is None (gateway handshake incomplete)")
    return sid


@client.event
async def on_ready():
    c = _cfg()
    # discord.py-self guarantees client.user is populated by the time on_ready
    # fires; assert it so the user_id reads below are not None-typed.
    assert client.user is not None
    log.info(f"Discord connected as {client.user} (id={client.user.id})")
    log.info(f"Watching channel {c.channel_id}")
    emit("DISCORD_CONNECTED", user_id=str(client.user.id))
    runtime._ready.set()


@client.event
async def on_disconnect():
    """Clear the readiness flag the moment the gateway drops.

    discord.py-self's internal reconnect logic handles transient drops without
    bouncing the process; while it's reconnecting, ``client.ws.session_id``
    may be ``None`` and any interaction call we attempt will 401. Gating
    /imagine on ``_ready.is_set()`` returns a clean 503 DISCORD_NOT_READY
    instead of leaking an AttributeError.
    """
    was_ready = runtime._ready.is_set()
    runtime._ready.clear()
    if was_ready:
        # Only announce drops we actually noticed (suppress the noise of a
        # reconnect attempt that briefly fires on_disconnect before on_ready).
        emit("DISCORD_DISCONNECTED", reason="on_disconnect")


@client.event
async def on_message(message):
    # Imported lazily, not at module top: ingest -> discord_send -> discord_client
    # would otherwise form an import cycle (discord_send needs ``client`` /
    # ``_session_id_or_raise`` from this module). Deferring the ingest import to
    # call time keeps the module-level graph acyclic.
    from cascade_img.backends.midjourney_discord.ingest.messages import _ingest_message

    loop = asyncio.get_running_loop()
    await loop.run_in_executor(runtime._POOLS["ingest"], _ingest_message, message)


@client.event
async def on_message_edit(before, after):
    from cascade_img.backends.midjourney_discord.ingest.messages import _ingest_message

    loop = asyncio.get_running_loop()
    # Pass event="edit" so the raw capture distinguishes MJ's in-place
    # progress edits from fresh messages. discord.Message is __slots__-based,
    # so the tag rides as a call argument, not an attribute.
    await loop.run_in_executor(runtime._POOLS["ingest"], _ingest_message, after, "edit")


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
    return bool(isinstance(exc, discord.HTTPException) and getattr(exc, "status", None) == 401)


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
    runtime._loop_holder["loop"] = loop

    # Separate pools (see _POOLS). Ingest is wide because each worker can sit on
    # a download or a 35s press-gather; HTTP is small — it only does the short
    # interaction round-trips that ingest waits on, so it must never be the pool
    # ingest is also competing for.
    runtime._POOLS["ingest"] = ThreadPoolExecutor(max_workers=64, thread_name_prefix="mj-ingest")
    runtime._POOLS["http"] = ThreadPoolExecutor(max_workers=16, thread_name_prefix="mj-http")

    attempt = 0
    try:
        while not runtime._shutdown_event.is_set():
            attempt += 1
            try:
                loop.run_until_complete(client.start(c.discord_token))
                # Returned without raising — gateway closed cleanly. _ready
                # may have been cleared by on_disconnect; if not, clear here.
                runtime._ready.clear()
                emit("DISCORD_DISCONNECTED", reason="gateway_close")
            except BaseException as e:
                runtime._ready.clear()
                if _is_terminal_auth_failure(e):
                    log.error(f"Discord auth rejected (terminal): {type(e).__name__}: {e}")
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

            if runtime._shutdown_event.is_set():
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
            log.info(f"Reconnecting to Discord in {backoff:.0f}s (attempt {attempt + 1})")
            # Sleep on _shutdown_event so SIGINT/SIGTERM cuts the wait short.
            if runtime._shutdown_event.wait(timeout=backoff):
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
        runtime._loop_holder["loop"] = None
        with contextlib.suppress(Exception):
            # Cancel anything still pending on the loop before closing.
            for task in asyncio.all_tasks(loop):
                task.cancel()
        with contextlib.suppress(Exception):
            loop.run_until_complete(loop.shutdown_asyncgens())
        with contextlib.suppress(Exception):
            if not loop.is_closed():
                loop.close()
        # Drop the worker pools so their threads don't outlive the loop. Don't
        # block on in-flight downloads (they carry their own 30s timeouts).
        for key in ("ingest", "http"):
            pool = runtime._POOLS[key]
            runtime._POOLS[key] = None
            if pool is not None:
                with contextlib.suppress(Exception):
                    pool.shutdown(wait=False, cancel_futures=True)

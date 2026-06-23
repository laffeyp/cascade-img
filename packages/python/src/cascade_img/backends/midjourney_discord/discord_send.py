"""Outbound Discord Interactions-API senders.

Extracted from bridge.py (sprint 023.8). These four coroutines fire the
``/imagine`` slash command, press message-component buttons, post arbitrary
interaction payloads, and fetch a channel message for its live components. They
depend only on config / runtime / the Discord client — no job shape — so ingest
(which calls ``_press_button``) and the routes can import them downward, cutting
the ``ingest -> discord_send -> ... -> ingest`` cycle.

Binding discipline: ``_cfg()`` is the config accessor (``cfg`` is reassigned at
startup); the loop/pool holders come from ``runtime``; the live ``client`` and
``_session_id_or_raise`` come from ``discord_client`` so the suite's
``client.ws`` patches reach them.
"""

from __future__ import annotations

import asyncio

import requests

from cascade_img.backends.midjourney_discord import runtime
from cascade_img.backends.midjourney_discord.config import MJ_BOT_ID, _cfg
from cascade_img.backends.midjourney_discord.discord_client import (
    _session_id_or_raise,
    client,
)

# Discord Interactions API constants (per
# https://discord.com/developers/docs/interactions/receiving-and-responding).
_INTERACTION_APPLICATION_COMMAND = 2  # slash-command invocation
_INTERACTION_MESSAGE_COMPONENT = 3  # button / select-menu interaction
_COMPONENT_TYPE_BUTTON = 2
_OPTION_TYPE_STRING = 3


async def _post_interaction(payload: dict) -> requests.Response:
    c = _cfg()
    headers = {"Authorization": c.discord_token, "Content-Type": "application/json"}
    loop = asyncio.get_running_loop()
    # On the HTTP pool, never the ingest pool: an ingest thread blocked waiting
    # on this very call must not be competing with it for a worker.
    return await loop.run_in_executor(
        runtime._POOLS["http"],
        lambda: requests.post(
            "https://discord.com/api/v9/interactions",
            json=payload,
            headers=headers,
            timeout=30,
        ),
    )


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
                    {
                        "type": _OPTION_TYPE_STRING,
                        "name": "prompt",
                        "description": "The prompt to imagine",
                    }
                ],
            },
        },
    }
    # Required by Discord when the channel lives in a guild — without it the
    # API treats the call as a DM and returns 400 Unknown Channel.
    if c.guild_id:
        payload["guild_id"] = c.guild_id
    return await _post_interaction(payload)


async def _press_button(message_id: int, custom_id: str, guild_id: str | None) -> requests.Response:
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


async def _fetch_message(message_id: int):
    """Fetch a channel message by id so its *current* components can be read.

    Runs on the Discord loop. /action needs the live custom_ids, and a SOLO
    upscaled-image message may have left the in-memory message cache, so this
    falls back to a REST fetch of the channel and the message.
    """
    c = _cfg()
    channel = client.get_channel(c.channel_id) or await client.fetch_channel(c.channel_id)
    # The configured channel is a messageable text channel; the get/fetch return
    # type is the full channel union (some members lack fetch_message).
    return await channel.fetch_message(message_id)  # type: ignore[union-attr]

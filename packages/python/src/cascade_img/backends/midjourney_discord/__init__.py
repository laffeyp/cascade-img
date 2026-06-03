"""Midjourney backend implementation.

Drives Midjourney through a Discord user account using ``discord.py-self``.
The package is structured around three responsibilities:

* ``bridge.py`` is the long-running Flask daemon that holds the Discord
  WebSocket session, fires ``/imagine`` interactions, watches the channel
  for grid messages, downloads PNGs, and presses upscale buttons. It also
  declares the environment-variable contract (:class:`Config`,
  :class:`MissingEnvError`).
* ``bridge_client.py`` defines :class:`MidjourneyDiscordBackend`, the
  :class:`~cascade_img.backends.base.ImageGenerationBackend` subclass that
  speaks HTTP to a running bridge.
* ``job_store.py`` is the SQLite-backed durable mirror of in-flight jobs.
  It records each job's prompt, state, grid message, and downloaded results
  so the bridge can survive a restart and rehydrate work that was still
  pending, rather than losing track of interactions already sent to Discord.

ToS note: this drives a Discord user account against Midjourney, which both
services' Terms of Service prohibit; see ``TOS.md``.
"""

from cascade_img.backends.midjourney_discord.bridge import Config, MissingEnvError
from cascade_img.backends.midjourney_discord.bridge_client import (
    MIDJOURNEY_DISCORD_CAPABILITIES,
    MidjourneyDiscordBackend,
)

__all__ = [
    "MIDJOURNEY_DISCORD_CAPABILITIES",
    "Config",
    "MidjourneyDiscordBackend",
    "MissingEnvError",
]

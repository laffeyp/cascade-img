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

ToS context: Midjourney has no public API; driving it through a Discord
user account is the established OSS pattern. Both Discord's and Midjourney's
Terms of Service prohibit user-account automation. See ``TOS.md`` at the
repository root.
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

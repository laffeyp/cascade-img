"""Midjourney backend implementation.

Drives Midjourney through a Discord user account using ``discord.py-self``.
The module is structured around three responsibilities:

* ``bridge.py`` is the long-running Flask daemon that holds the Discord
  WebSocket session, fires ``/imagine`` interactions, watches the channel
  for grid messages, downloads PNGs, and presses upscale buttons.
* ``backend.py`` defines :class:`MidjourneyDiscordBackend`, the
  :class:`~cascade_img.backends.base.ImageGenerationBackend` subclass that
  speaks HTTP to a running bridge.
* ``config.py`` (loaded transitively via ``bridge``) declares the
  environment-variable contract.

ToS context: Midjourney has no public API; driving it through a Discord
user account is the established OSS pattern. Both Discord's and Midjourney's
Terms of Service prohibit user-account automation. See ``TOS.md`` at the
repository root.
"""

from cascade_img.backends.midjourney_discord.backend import (
    MIDJOURNEY_DISCORD_CAPABILITIES,
    MidjourneyDiscordBackend,
)
from cascade_img.backends.midjourney_discord.bridge import Config, MissingEnvError

__all__ = [
    "MIDJOURNEY_DISCORD_CAPABILITIES",
    "Config",
    "MidjourneyDiscordBackend",
    "MissingEnvError",
]

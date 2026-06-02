"""Midjourney-via-Discord backend.

The OSS path to programmatic Midjourney access. Drives MJ through a Discord
user account using ``discord.py-self``. See ``bridge.py`` for the Flask daemon
that fronts the WebSocket and ``client.py`` for the thin HTTP helper, with
:class:`MidjourneyDiscordBackend` in ``backend.py`` as the conforming
:class:`~cascade_img.backends.base.ImageGenerationBackend` subclass.

ToS posture: this is automation of a Discord account (prohibited by Discord)
and automation of Midjourney (prohibited by Midjourney). Use a sacrificial
Discord account. The pluggable-backend design exists in part so users who
want a sanctioned alternative can swap to Flux, DALL-E, Imagen, etc.
"""

from cascade_img.backends.midjourney_discord.backend import (
    MIDJOURNEY_DISCORD_CAPABILITIES,
    MidjourneyDiscordBackend,
)
from cascade_img.backends.midjourney_discord.bridge import Config, MissingEnvError

__all__ = [
    "MidjourneyDiscordBackend",
    "MIDJOURNEY_DISCORD_CAPABILITIES",
    "Config",
    "MissingEnvError",
]

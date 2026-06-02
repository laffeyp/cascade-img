"""Backend interface for image-generation providers.

v0.1 ships :class:`cascade_img.backends.midjourney_discord.MidjourneyDiscordBackend`
only. The abstract is intentionally small — two async methods and a
capabilities declaration — because a second backend hasn't shipped yet and
the speculative surface would harden into something wrong. When Flux,
DALL-E, or Imagen lands, this file grows from observed need.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BackendCapabilities:
    """What a backend declares about itself.

    Declarative metadata attached to each :class:`ImageGenerationBackend`
    subclass. v0.1 records the supported composable prompt parts (moodboard,
    sref, oref, ow, style_raw, stylize, etc.) and aspect ratios. Future
    versions can grow the surface when a consumer demands it (a capability-
    aware composer or an MCP introspection tool); v0.1 keeps the declaration
    honest without speculative consumers."""

    prompt_parts: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)


class ImageGenerationBackend(ABC):
    """Minimal v0.1 surface: submit a job, await its result.

    Methods are **synchronous** at v0.1. Callers needing asyncio responsiveness
    invoke via ``asyncio.to_thread(backend.imagine, ...)``. Honest API rather
    than ``async def`` wrapping blocking ``requests`` calls."""

    capabilities: BackendCapabilities

    @abstractmethod
    def imagine(self, prompt: str, asset_id: str, upscale=None):
        """Submit a generation. Returns a handle whose ``job_id`` is passed to :meth:`wait`."""

    @abstractmethod
    def wait(self, job_id: str, timeout: int = 180) -> dict:
        """Block until the job hits ``done`` or ``failed`` or the timeout fires."""

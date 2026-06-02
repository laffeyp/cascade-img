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
    """What a backend can do. Read by the prompt composer (to decide which
    facets to include) and by the MCP ``list_backends`` tool (so agents can
    introspect)."""

    facets: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)


class ImageGenerationBackend(ABC):
    """Minimal v0.1 surface: submit a job, await its result."""

    capabilities: BackendCapabilities

    @abstractmethod
    async def imagine(self, prompt: str, asset_id: str, upscale=None):
        """Submit a generation. Returns a handle whose ``job_id`` is passed to :meth:`wait`."""

    @abstractmethod
    async def wait(self, job_id: str, timeout: int = 180) -> dict:
        """Block until the job hits ``done`` or ``failed`` or the timeout fires."""

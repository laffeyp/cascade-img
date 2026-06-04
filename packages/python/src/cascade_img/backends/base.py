"""Backend interface for image-generation providers.

v0.1 ships :class:`cascade_img.backends.midjourney_discord.MidjourneyDiscordBackend`
only. The surface is deliberately small — a synchronous
``imagine`` / ``wait`` / ``status`` / ``health`` plus a capabilities
declaration — and grows when a second backend lands.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BackendCapabilities:
    """What a backend declares about itself.

    v0.1 records the supported composable prompt parts (moodboard, sref, oref,
    ow, style_raw, stylize) and aspect ratios."""

    prompt_parts: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)


class ImageGenerationBackend(ABC):
    """Minimal v0.1 surface: submit a job, await its result, read status, report health.

    Methods are **synchronous**. Callers needing asyncio responsiveness invoke
    via ``asyncio.to_thread(backend.imagine, ...)`` rather than wrapping blocking
    ``requests`` calls in ``async def``."""

    capabilities: BackendCapabilities

    @abstractmethod
    def imagine(self, prompt: str, asset_id: str, upscale=None):
        """Submit a generation. Returns a handle whose ``job_id`` is passed to :meth:`wait`."""

    @abstractmethod
    def wait(self, job_id: str, timeout: int = 180) -> dict:
        """Block until the job hits ``done`` or ``failed`` or the timeout fires."""

    @abstractmethod
    def status(self, job_id: str) -> dict:
        """Non-blocking read of the job's current state (the ``status`` MCP tool)."""

    @abstractmethod
    def health(self) -> dict:
        """Report backend liveness — daemon up, upstream connected (``bridge_health``)."""

"""Abstract base class for image-generation backends.

This is the pluggable seam. A backend is anything that can take a
backend-specific prompt string (composed by :class:`cascade_img.composer.PromptComposer`
from structured facets) and return a :class:`Job` whose result can be awaited
and inspected. v0.1 ships :class:`cascade_img.backends.midjourney_discord` only;
later versions add Flux, DALL-E, Imagen, Ideogram, Recraft, and others behind
the same interface.

Adding a backend means subclassing :class:`ImageGenerationBackend`, declaring
:class:`BackendCapabilities`, and implementing the four async methods. Nothing
above this seam in the architecture knows which backend is active.

This file is currently a skeleton. The contract surface is locked at v0.1 and
the concrete shapes (``Job``, ``JobResult``, ``JobStatus``, ``HealthReport``,
``BackendCapabilities``) are filled in during the Phase 3 refactor pass that
follows this scaffold commit.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field


@dataclass
class BackendCapabilities:
    """What a backend can do.

    Filled in during the refactor pass. Placeholders left here so importers
    don't break.
    """

    facets: list[str] = field(default_factory=list)
    aspect_ratios: list[str] = field(default_factory=list)


class ImageGenerationBackend(ABC):
    """Pluggable backend interface.

    Skeleton form. Methods are declared so subclasses can begin to take shape;
    the concrete signatures (return types, parameter names) are finalized in
    the refactor pass that wraps the MJ daemon in a conforming subclass.
    """

    capabilities: BackendCapabilities

    @abstractmethod
    async def imagine(self, prompt: str, asset_id: str, upscale):
        """Fire a generation. Returns a job handle."""

    @abstractmethod
    async def wait(self, job_id: str, timeout: int):
        """Block until the job reaches ``done`` or ``failed`` (or timeout)."""

    @abstractmethod
    async def status(self, job_id: str):
        """Non-blocking status read."""

    @abstractmethod
    async def health(self):
        """Backend health, including whether it can reach the upstream service."""

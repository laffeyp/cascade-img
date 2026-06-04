"""Backend interface and implementations.

A backend is the boundary between the orchestration layer (composer, client,
curation, log, MCP server) and a specific image-generation provider. v0.1 ships
the Midjourney-via-Discord backend; other providers (Flux, DALL-E, Imagen)
implement the same interface.
"""

from cascade_img.backends.base import ImageGenerationBackend

__all__ = ["ImageGenerationBackend"]

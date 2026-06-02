"""Backend interface and implementations.

Backends are the pluggable seam between the orchestration layer (composer,
client, curation, log, MCP server) and a specific image-generation provider.
v0.1 ships the Midjourney-via-Discord backend. Flux, DALL-E, Stable Diffusion,
Imagen, Ideogram, Recraft, and an official MJ Enterprise backend are planned.

Adding a backend is a few hundred lines of HTTP wrapping plus a capability
declaration. Everything above this seam in the architecture is backend-agnostic.
"""

from cascade_img.backends.base import ImageGenerationBackend

__all__ = ["ImageGenerationBackend"]

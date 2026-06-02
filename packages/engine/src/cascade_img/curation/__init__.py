"""Curation utilities for Midjourney grid outputs.

* :func:`crop_quadrant` extracts one of the four 2x2 grid panels.
  ``quadrant=0`` returns the whole image (used for the ``--upscale 1`` path
  that bypasses the grid).
* :func:`alpha_key_corners` performs corner-anchored background detection
  and alpha-keying for sprite-style outputs. Defaults to a flood-fill from
  each corner so subject regions surrounded by a darker outline stay
  opaque; a global-threshold fallback is available via ``method="threshold"``.
* :func:`promote` copies a curated image into the consumer's asset tree.
"""

from cascade_img.curation.alpha_key import DEFAULT_TOLERANCE, alpha_key_corners
from cascade_img.curation.crop_grid import QUADRANT_OFFSETS, crop_quadrant
from cascade_img.curation.promote import promote

__all__ = [
    "DEFAULT_TOLERANCE",
    "QUADRANT_OFFSETS",
    "alpha_key_corners",
    "crop_quadrant",
    "promote",
]

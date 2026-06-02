"""Curation utilities for Midjourney grid outputs.

* :func:`crop_quadrant` extracts one of the four 2x2 grid panels.
  ``quadrant=0`` returns the whole image (used for the ``--upscale 1`` path
  that bypasses the grid).
* :func:`alpha_key_corners` performs corner-anchored background detection and
  alpha-keying for sprite-style outputs (``flood`` default, ``threshold``
  fallback, or ``rembg`` ML removal via the optional ``[ml]`` extra).
* :func:`contact_sheet` composites a grid's panels into one labelled image for
  vision-model selection.
* :func:`auto_trim` crops an image to its content bounding box.
* :func:`palette_quantize` reduces an image to a fixed palette.
* :func:`sprite_sheet` packs several sprites into one atlas plus a frame map.
* :func:`promote` copies a curated image into the consumer's asset tree.
"""

from cascade_img.curation.alpha_key import DEFAULT_TOLERANCE, alpha_key_corners
from cascade_img.curation.auto_trim import auto_trim
from cascade_img.curation.contact_sheet import contact_sheet
from cascade_img.curation.crop_grid import QUADRANT_OFFSETS, crop_quadrant
from cascade_img.curation.palette_quantize import palette_quantize
from cascade_img.curation.promote import promote
from cascade_img.curation.sprite_sheet import sprite_sheet

__all__ = [
    "DEFAULT_TOLERANCE",
    "QUADRANT_OFFSETS",
    "alpha_key_corners",
    "auto_trim",
    "contact_sheet",
    "crop_quadrant",
    "palette_quantize",
    "promote",
    "sprite_sheet",
]

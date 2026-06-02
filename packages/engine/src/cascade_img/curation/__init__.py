"""Curation utilities for MJ grid outputs.

Three independently usable functions:

* :func:`crop_quadrant` — pull one of the four 2x2 grid panels out as a
  standalone image. ``quadrant=0`` returns the whole image (for the
  ``--upscale 1`` path that bypasses the grid).
* :func:`alpha_key_corners` — four-corner-average background detection and
  alpha-keying. The practical fix for MJ ignoring "transparent background"
  about half the time on sprite-style art.
* :func:`promote` — move a curated winner from a staging path into the
  consumer's asset tree.

The library is project-agnostic. the demo's ``PROMOTION`` and ``ALPHA_KEY``
maps live in ``examples/demo/curation_config.py``, not here.
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

"""Curation — post-generation image steps for Midjourney grid outputs.

Grouped by theme; this facade re-exports every step so callers keep using
``from cascade_img.curation import <step>`` regardless of which subpackage now
hosts it.

* ``geometry/`` — reshape pixel extent: :func:`crop_quadrant` (one of the four
  2x2 grid panels; ``quadrant=0`` is a whole-image passthrough for the
  ``--upscale 1`` path), :func:`auto_trim` (crop to the content bounding box).
* ``color/`` — :func:`alpha_key_corners` (corner-anchored background keying;
  ``flood`` default, ``threshold`` fallback, or ``rembg`` ML removal via the
  optional ``[ml]`` extra), :func:`palette_quantize` (fixed-palette reduction).
* ``sheets/`` — composite many inputs into one: :func:`contact_sheet` (labelled
  2x2 review sheet for vision-model selection), :func:`sprite_sheet` (atlas plus
  a frame map).
* ``select/`` — :func:`score_grid` (rank a grid's quadrants, pure-PIL),
  :func:`promote` (copy a curated image into the consumer's asset tree).
* ``video/`` — make a temporal artifact inspectable: :func:`video_filmstrip`
  (sample keyframes into a vision-readable contact sheet + signature, F32),
  :func:`loop_seam_delta` (report a looping video's seam cleanliness as a
  number, F33).

Primitives shared by more than one theme (``QUADRANT_OFFSETS`` and the
corner-background sampler) live in the private :mod:`._shared` module so the
subpackages depend on a common module instead of reaching into each other.
"""

from cascade_img.curation._shared import QUADRANT_OFFSETS
from cascade_img.curation.color import DEFAULT_TOLERANCE, alpha_key_corners, palette_quantize
from cascade_img.curation.geometry import auto_trim, crop_quadrant
from cascade_img.curation.select import promote, score_grid
from cascade_img.curation.sheets import contact_sheet, sprite_sheet
from cascade_img.curation.video import loop_seam_delta, video_filmstrip

__all__ = [
    "DEFAULT_TOLERANCE",
    "QUADRANT_OFFSETS",
    "alpha_key_corners",
    "auto_trim",
    "contact_sheet",
    "crop_quadrant",
    "loop_seam_delta",
    "palette_quantize",
    "promote",
    "score_grid",
    "sprite_sheet",
    "video_filmstrip",
]

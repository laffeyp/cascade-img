"""Color curation — alpha-channel keying and palette reduction.

* :func:`alpha_key_corners` performs corner-anchored background detection and
  alpha-keying for sprite-style outputs.
* :func:`palette_quantize` reduces an image to a fixed palette.
"""

from cascade_img.curation.color.alpha_key import DEFAULT_TOLERANCE, alpha_key_corners
from cascade_img.curation.color.palette_quantize import palette_quantize

__all__ = ["DEFAULT_TOLERANCE", "alpha_key_corners", "palette_quantize"]

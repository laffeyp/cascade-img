"""Geometry curation — reshape an image's pixel extent.

* :func:`crop_quadrant` extracts one of the four 2x2 grid panels.
* :func:`auto_trim` crops an image to its content bounding box.
"""

from cascade_img.curation.geometry.auto_trim import auto_trim
from cascade_img.curation.geometry.grid_crop import crop_quadrant

__all__ = ["auto_trim", "crop_quadrant"]

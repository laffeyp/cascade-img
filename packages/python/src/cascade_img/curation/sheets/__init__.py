"""Sheet curation — composite many inputs into one image.

* :func:`contact_sheet` composites a grid's panels into one labelled image for
  vision-model selection.
* :func:`sprite_sheet` packs several sprites into one atlas plus a frame map.
"""

from cascade_img.curation.sheets.contact_sheet import contact_sheet
from cascade_img.curation.sheets.sprite_sheet import sprite_sheet

__all__ = ["contact_sheet", "sprite_sheet"]

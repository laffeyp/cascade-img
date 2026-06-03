"""Selection curation — rank candidates, then publish the chosen asset.

* :func:`score_grid` ranks a grid's quadrants for selection (pure-PIL).
* :func:`promote` copies a curated image into the consumer's asset tree.
"""

from cascade_img.curation.select.promote import promote
from cascade_img.curation.select.score_grid import score_grid

__all__ = ["promote", "score_grid"]

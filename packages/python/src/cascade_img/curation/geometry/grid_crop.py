"""Quadrant cropper for MJ 2x2 grids.

MJ grids are laid out (top-left origin, U1..U4)::

    U1 U2
    U3 U4

``quadrant=0`` is a passthrough for the ``--upscale 1`` path where the bridge
already returned a single upscale and no crop is needed — keeping the API
uniform across the two output shapes.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from cascade_img.curation._shared import QUADRANT_OFFSETS
from cascade_img.vocabulary import emit


def crop_quadrant(src: str | Path | Image.Image, quadrant: int) -> Image.Image:
    """Crop one quadrant of an MJ 2x2 grid.

    Args:
        src: Path to grid PNG/WebP or a PIL Image already loaded.
        quadrant: 0 (whole image — for single upscales) or 1-4 (grid quadrant).

    Returns:
        Cropped PIL Image.

    Raises:
        ValueError: quadrant is not 0 or 1-4.
        FileNotFoundError: src path does not exist.
    """
    # When given a path, ``Image.open`` returns a lazy loader that must be
    # closed (or used as a context manager) to release the file descriptor.
    # Review-flagged 2026-06-02 (FD leak on repeated crops).
    opened_here = False
    img: Image.Image  # Image.open returns the ImageFile subclass; widen the var
    if isinstance(src, (str, Path)):
        img = Image.open(src)
        opened_here = True
    else:
        img = src

    try:
        if quadrant == 0:
            # Materialize into RAM and close the file-backed loader.
            out = img.copy() if opened_here else img
            emit("CROP_QUADRANT", quadrant=0, w=out.size[0], h=out.size[1])
            return out

        if quadrant not in QUADRANT_OFFSETS:
            raise ValueError(f"quadrant must be 0 (whole image) or 1-4, got {quadrant}")

        w, h = img.size
        qw, qh = w // 2, h // 2
        fx, fy = QUADRANT_OFFSETS[quadrant]
        # Right/bottom quadrants extend to the full edge so odd-dimension grids
        # don't silently lose their last pixel column/row to the // 2 floor.
        box = (
            fx * qw,
            fy * qh,
            w if fx else qw,
            h if fy else qh,
        )
        cropped = img.crop(box)
        emit("CROP_QUADRANT", quadrant=quadrant, w=cropped.size[0], h=cropped.size[1])
        return cropped
    finally:
        if opened_here:
            img.close()

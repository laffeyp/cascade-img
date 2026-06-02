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
from typing import Union

from PIL import Image

from cascade_img.instrumentation.runtime import emit

# MJ grid layout (top-left origin). Each tuple is (column_fraction, row_fraction).
QUADRANT_OFFSETS: dict[int, tuple[int, int]] = {
    1: (0, 0),  # top-left      U1
    2: (1, 0),  # top-right     U2
    3: (0, 1),  # bottom-left   U3
    4: (1, 1),  # bottom-right  U4
}


def crop_quadrant(src: Union[str, Path, Image.Image], quadrant: int) -> Image.Image:
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
    if isinstance(src, (str, Path)):
        img = Image.open(src)
    else:
        img = src

    if quadrant == 0:
        emit("CROP_QUADRANT", quadrant=0, w=img.size[0], h=img.size[1])
        return img

    if quadrant not in QUADRANT_OFFSETS:
        raise ValueError(f"quadrant must be 0 (whole image) or 1-4, got {quadrant}")

    w, h = img.size
    qw, qh = w // 2, h // 2
    fx, fy = QUADRANT_OFFSETS[quadrant]
    box = (fx * qw, fy * qh, fx * qw + qw, fy * qh + qh)
    cropped = img.crop(box)
    emit("CROP_QUADRANT", quadrant=quadrant, w=cropped.size[0], h=cropped.size[1])
    return cropped

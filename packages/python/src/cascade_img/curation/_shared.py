"""Primitives shared across more than one curation theme.

Lifted here so the themed subpackages (``geometry/``, ``color/``, ``sheets/``,
``select/``) depend on one common module instead of reaching sideways into a
sibling theme:

* :data:`QUADRANT_OFFSETS` — the MJ 2x2 grid layout. Used by ``geometry``
  (quadrant crop), ``sheets`` (contact-sheet badges), and ``select`` (scoring).
* :func:`_sample_bg` — the four-corner-average background color. Used by
  ``color`` (alpha keying) and ``geometry`` (color-mode auto-trim). Its pixel
  helpers (:func:`_pixels`, :func:`_rgba_components`) travel with it so this
  module has no back-dependency on ``color/``.

Private (underscore): these are internal helpers, not part of the public
curation API. The public re-exports live in ``curation/__init__.py``.
"""

from __future__ import annotations

from typing import Any

from PIL import Image

# MJ grid layout (top-left origin). Each tuple is (col_index, row_index), 0 or 1.
#
#     U1 U2
#     U3 U4
QUADRANT_OFFSETS: dict[int, tuple[int, int]] = {
    1: (0, 0),  # top-left      U1
    2: (1, 0),  # top-right     U2
    3: (0, 1),  # bottom-left   U3
    4: (1, 1),  # bottom-right  U4
}


def _pixels(img: Image.Image) -> Any:
    """``img.load()`` typed as ``Any``.

    Pillow types the C pixel accessor as ``PixelAccess | None`` and does not
    express its ``px[x, y]`` get/set subscript API, so a typed accessor trips
    mypy on every pixel touch. The accessor is non-None for any loaded image
    (load() returns None only for a closed/zero-size image, which the callers
    already guard) and supports get/set at runtime."""
    px = img.load()
    if px is None:  # closed or zero-size image
        raise ValueError("alpha_key: image has no pixel access (closed or zero-size)")
    return px


def _rgba_components(pixel, mode: str) -> tuple[int, int, int, int]:
    """Normalize PIL pixel-access output to (r, g, b, a).

    ``convert("RGBA")`` is well-defined for ordinary inputs but some modes
    (P with single-channel transparency, corrupt files) yield 3-channel
    tuples. Tolerate >=3 channels; default alpha to 255 when absent.
    """
    if len(pixel) >= 4:
        return pixel[0], pixel[1], pixel[2], pixel[3]
    if len(pixel) == 3:
        return pixel[0], pixel[1], pixel[2], 255
    raise ValueError(
        f"alpha_key_corners: pixel access returned {len(pixel)}-channel data; "
        f"image mode={mode!r}; expected RGB or RGBA after convert('RGBA')."
    )


def _sample_bg(rgba: Image.Image) -> tuple[int, int, int]:
    """Four-corner-average background color in 0-255 RGB space."""
    px = _pixels(rgba)
    w, h = rgba.size
    corners = (px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1])
    rs = [_rgba_components(c, rgba.mode) for c in corners]
    return (
        sum(c[0] for c in rs) // 4,
        sum(c[1] for c in rs) // 4,
        sum(c[2] for c in rs) // 4,
    )

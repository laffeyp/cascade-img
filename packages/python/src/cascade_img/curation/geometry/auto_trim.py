"""Crop an image to its content bounding box.

``mode="alpha"`` trims to the non-transparent extent — the right step right
after :func:`alpha_key_corners`, to tighten a keyed sprite to its pixels.
``mode="color"`` detects the corner-average background and trims to the first
pixels that differ from it beyond ``tolerance``. When there is nothing to trim
to (a blank or fully transparent image) the original extent is kept.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops

from cascade_img.curation._shared import _sample_bg
from cascade_img.vocabulary import emit


def auto_trim(
    src: str | Path,
    dest: str | Path,
    *,
    mode: str = "alpha",
    tolerance: int = 10,
) -> Path:
    """Crop ``src`` to its content bounding box and write it to ``dest``.

    Args:
        src: Path to the image.
        dest: Output path for the trimmed image.
        mode: ``"alpha"`` (non-transparent extent) or ``"color"`` (distance
            from the corner-average background).
        tolerance: For ``"color"`` mode, the per-pixel distance from the
            background that still counts as background.

    Returns:
        The resolved ``dest`` path.
    """
    src_p, dest_p = Path(src), Path(dest)
    with Image.open(src_p) as im:
        img = im.convert("RGBA")

    w0, h0 = img.size
    if mode == "alpha":
        bbox = img.getchannel("A").getbbox()
    elif mode == "color":
        bg = _sample_bg(img)
        bg_img = Image.new("RGB", img.size, bg)
        diff = ImageChops.difference(img.convert("RGB"), bg_img).convert("L")
        mask = diff.point(lambda p: 255 if p > tolerance else 0)
        bbox = mask.getbbox()
    else:
        raise ValueError(f"auto_trim: unknown mode {mode!r}; expected 'alpha' or 'color'.")

    if bbox is None:
        bbox = (0, 0, w0, h0)
    out = img.crop(bbox)

    dest_p.parent.mkdir(parents=True, exist_ok=True)
    out.save(dest_p)
    emit(
        "AUTO_TRIM_APPLIED",
        src=str(src_p),
        dest=str(dest_p),
        bbox=list(bbox),
        w=out.size[0],
        h=out.size[1],
    )
    return dest_p

"""Four-corner-average alpha keyer for sprite-style outputs.

Samples the four corner pixels of the image, averages their RGB to estimate
the background color, then sets alpha=0 on every pixel within ``tolerance``
per channel of that color. Default tolerance 40 (0-255 range): too tight
leaves a halo around the subject, too loose eats into it.

Not appropriate for full-scene images where the entire frame is the asset.
Apply selectively, per asset, in the consumer's curation flow.
"""

from __future__ import annotations

from PIL import Image

from cascade_img.vocabulary import emit

DEFAULT_TOLERANCE = 40


def alpha_key_corners(
    img: Image.Image, tolerance: int = DEFAULT_TOLERANCE
) -> Image.Image:
    """Apply four-corner-average alpha keying.

    Args:
        img: PIL Image (any mode; converted to RGBA internally).
        tolerance: Per-channel tolerance band around the sampled background.

    Returns:
        RGBA Image with background pixels set to alpha=0.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    if px is None or w == 0 or h == 0:
        return rgba

    # ``convert("RGBA")`` is well-defined for ordinary inputs but some modes
    # (P with single-channel transparency, corrupt files) yield 3-channel
    # tuples. Tolerate >=3 channels; default alpha to 255 when absent.
    def _rgba(pixel):
        if len(pixel) >= 4:
            return pixel[0], pixel[1], pixel[2], pixel[3]
        if len(pixel) == 3:
            return pixel[0], pixel[1], pixel[2], 255
        raise ValueError(
            f"alpha_key_corners: pixel access returned {len(pixel)}-channel data; "
            f"image mode={rgba.mode!r}; expected RGB or RGBA after convert('RGBA')."
        )

    cr = [_rgba(c) for c in (px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1])]
    bg_r = sum(c[0] for c in cr) // 4
    bg_g = sum(c[1] for c in cr) // 4
    bg_b = sum(c[2] for c in cr) // 4

    keyed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, _a = _rgba(px[x, y])
            if (
                abs(r - bg_r) <= tolerance
                and abs(g - bg_g) <= tolerance
                and abs(b - bg_b) <= tolerance
            ):
                px[x, y] = (r, g, b, 0)
                keyed += 1

    total = w * h
    emit(
        "ALPHA_KEY_APPLIED",
        tolerance=tolerance,
        bg_r=bg_r,
        bg_g=bg_g,
        bg_b=bg_b,
        keyed_count=keyed,
        total_count=total,
    )
    return rgba

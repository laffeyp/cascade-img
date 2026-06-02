"""Four-corner-average alpha keyer for MJ sprite-style outputs.

MJ frequently ignores ``transparent background`` in the prompt and ships the
sprite on a near-uniform colored backdrop. Defensive post-process: sample the
four corner pixels of the image, average their RGB to get the background
color, then set alpha=0 on every pixel within ``tolerance`` per channel of
that color.

Tuned for MJ's sprite art, which has soft anti-aliased edges. Default
tolerance of 40 (0-255 range) is the calibration that came out of the default
— too tight leaves a halo, too loose eats into the sprite. Tighten via the
``tolerance`` arg for cleaner edges, loosen for backdrops with more variance.

This is NOT appropriate for full-scene region backdrops where the entire
image is the asset. Use the ``ALPHA_KEY`` per-asset gate in the consumer's
curation config to decide which assets get keyed.
"""

from __future__ import annotations

from PIL import Image

from cascade_img.instrumentation.runtime import emit

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

    # PIL's RGBA pixel access usually returns a 4-tuple, but ``convert("RGBA")``
    # on unusual inputs (palette mode P with single-channel transparency,
    # corrupted files, custom modes) may not produce the expected shape.
    # Use a small helper that tolerates >=3 channels (taking alpha=255 default)
    # and raises a clean error on <3. Review-flagged 2026-06-02.
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

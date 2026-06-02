"""Behavior contract for ``cascade_img.curation.alpha_key``."""

from __future__ import annotations

from PIL import Image

from cascade_img.curation import DEFAULT_TOLERANCE, alpha_key_corners
from cascade_img.instrumentation.sdd import clear, snapshot


def test_keys_uniform_background_keeps_center_opaque():
    """A uniform mid-gray background with a high-contrast center keys the
    background to alpha=0 and leaves the center opaque. The keyed ratio
    should be majority but not 100%."""
    clear()
    img = Image.new("RGB", (40, 40), (128, 128, 128))
    # Stamp a 10x10 hot-pink center.
    for y in range(15, 25):
        for x in range(15, 25):
            img.putpixel((x, y), (255, 0, 255))
    keyed = alpha_key_corners(img)
    assert keyed.size == (40, 40)
    assert keyed.mode == "RGBA"
    assert keyed.getpixel((0, 0))[3] == 0      # corner keyed
    assert keyed.getpixel((20, 20))[3] == 255  # center opaque
    records = snapshot()
    assert records[-1]["tag"] == "ALPHA_KEY_APPLIED"
    p = records[-1]["payload"]
    assert p["tolerance"] == DEFAULT_TOLERANCE
    assert p["bg_r"] == 128 and p["bg_g"] == 128 and p["bg_b"] == 128
    assert p["total_count"] == 1600
    # Most of the background (1500 px) is keyed; the 100 center pixels are not.
    assert 1400 <= p["keyed_count"] <= 1550


def test_handles_rgb_input_without_unpack_error():
    """convert('RGBA') usually returns 4-channel pixels, but unusual input
    modes can produce 3-channel pixels. The keyer's ``_rgba`` helper tolerates
    that rather than crashing with ``too many values to unpack``."""
    clear()
    img = Image.new("RGB", (10, 10), (200, 200, 200))
    out = alpha_key_corners(img)
    assert out.mode == "RGBA"
    assert out.getpixel((0, 0))[3] == 0


def test_respects_tolerance():
    """Tighter tolerance leaves more pixels opaque when the background has variance."""
    img = Image.new("RGB", (20, 20), (128, 128, 128))
    img.putpixel((0, 0), (160, 160, 160))  # noisy corner pixel
    keyed_tight = alpha_key_corners(img, tolerance=10)
    keyed_wide = alpha_key_corners(img, tolerance=80)
    tight_alpha_sum = sum(
        keyed_tight.getpixel((x, y))[3] for x in range(20) for y in range(20)
    )
    wide_alpha_sum = sum(
        keyed_wide.getpixel((x, y))[3] for x in range(20) for y in range(20)
    )
    assert tight_alpha_sum >= wide_alpha_sum

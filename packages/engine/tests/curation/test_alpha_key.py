"""Behavior contract for ``cascade_img.curation.alpha_key``."""

from __future__ import annotations

from PIL import Image

from cascade_img.curation import DEFAULT_TOLERANCE, alpha_key_corners
from cascade_img.vocabulary import clear, snapshot


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


def test_flood_keeps_white_interior_inside_dark_outline():
    """Subject color ≈ background color, separated by a dark outline.

    A white square outlined in near-black on a white background: the
    flood-fill keyer (default) must leave the white interior opaque
    because the outline blocks the flood. This is the case that exposed
    the threshold algorithm — the penguin with a white belly on a white
    background got the belly eaten by global thresholding.
    """
    img = Image.new("RGB", (40, 40), (255, 255, 255))
    # Draw a hollow dark-outlined square from (12,12) to (27,27).
    for i in range(12, 28):
        img.putpixel((i, 12), (10, 10, 10))
        img.putpixel((i, 27), (10, 10, 10))
        img.putpixel((12, i), (10, 10, 10))
        img.putpixel((27, i), (10, 10, 10))
    keyed = alpha_key_corners(img, tolerance=20)
    # Outer corner: pure white background, must be keyed.
    assert keyed.getpixel((0, 0))[3] == 0
    # Center of subject: white interior surrounded by the dark outline,
    # must remain opaque.
    assert keyed.getpixel((20, 20))[3] == 255
    # The outline pixels themselves are far from white; they stay opaque.
    assert keyed.getpixel((12, 20))[3] == 255


def test_threshold_method_eats_white_interior():
    """Regression-pin for the threshold algorithm: the same white-on-white
    case that flood-fill handles correctly is still eaten by the global
    threshold method. Documents the failure mode for callers who opt in
    to ``method='threshold'`` (e.g. when their domain has broken outlines
    that flood-fill would leak through)."""
    img = Image.new("RGB", (40, 40), (255, 255, 255))
    for i in range(12, 28):
        img.putpixel((i, 12), (10, 10, 10))
        img.putpixel((i, 27), (10, 10, 10))
        img.putpixel((12, i), (10, 10, 10))
        img.putpixel((27, i), (10, 10, 10))
    keyed = alpha_key_corners(img, tolerance=20, method="threshold")
    # Threshold sees corner-avg (white) and keys every white pixel,
    # including the interior — that's the failure flood-fill corrects.
    assert keyed.getpixel((0, 0))[3] == 0
    assert keyed.getpixel((20, 20))[3] == 0


def test_method_arg_validates():
    """Unknown method values raise ValueError at the keyer's mouth."""
    import pytest
    img = Image.new("RGB", (10, 10), (200, 200, 200))
    with pytest.raises(ValueError, match="unknown method"):
        alpha_key_corners(img, method="invalid")


def test_flood_handles_sentinel_collision_via_bfs_fallback():
    """If the source image contains the flood sentinel color (255, 0, 255),
    the keyer falls back to the pure-Python BFS so the result isn't
    contaminated by the sentinel-mark approach."""
    img = Image.new("RGB", (20, 20), (128, 128, 128))
    # Stamp a hot-pink center that collides with the sentinel.
    for y in range(8, 12):
        for x in range(8, 12):
            img.putpixel((x, y), (255, 0, 255))
    keyed = alpha_key_corners(img, tolerance=20)
    # Corner keyed (gray bg).
    assert keyed.getpixel((0, 0))[3] == 0
    # Pink center opaque — BFS path correctly skipped it.
    assert keyed.getpixel((10, 10))[3] == 255

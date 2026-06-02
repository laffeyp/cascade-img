"""Behavior contract for the curation kit.

Three independent functions, three independent signal payloads, three
independent tests. Each verifies (a) the function output is correct and
(b) the right signal fires with the right payload (the dual contract).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from cascade_img.curation import (
    DEFAULT_TOLERANCE,
    alpha_key_corners,
    crop_quadrant,
    promote,
)
from cascade_img.instrumentation.sdd import clear, snapshot


def _make_quadranted_grid(tmp_path: Path) -> Path:
    """100x100 image with four solid-color quadrants (TL=red, TR=green,
    BL=blue, BR=white). Used to verify each quadrant lands at the right
    output and isn't swapped with its neighbor."""
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    for y in range(50):
        for x in range(50):
            img.putpixel((x, y), (255, 0, 0))           # TL red
            img.putpixel((x + 50, y), (0, 255, 0))      # TR green
            img.putpixel((x, y + 50), (0, 0, 255))      # BL blue
            img.putpixel((x + 50, y + 50), (255, 255, 255))  # BR white
    p = tmp_path / "grid.png"
    img.save(p)
    return p


# --------------- crop_quadrant ---------------

def test_crop_quadrant_passthrough(tmp_path: Path):
    """quadrant=0 returns the whole image unchanged and emits w=full, h=full."""
    clear()
    src = _make_quadranted_grid(tmp_path)
    out = crop_quadrant(src, 0)
    assert out.size == (100, 100)
    records = snapshot()
    assert len(records) == 1
    assert records[0]["tag"] == "CROP_QUADRANT"
    assert records[0]["payload"] == {"quadrant": 0, "w": 100, "h": 100}


def test_crop_quadrant_returns_correct_quadrants(tmp_path: Path):
    """Each of U1..U4 returns the right corner color — proves the offsets
    aren't swapped (a swap was a real risk in the original since the
    offsets were a dict literal)."""
    src = _make_quadranted_grid(tmp_path)
    u1 = crop_quadrant(src, 1)   # top-left
    u2 = crop_quadrant(src, 2)   # top-right
    u3 = crop_quadrant(src, 3)   # bottom-left
    u4 = crop_quadrant(src, 4)   # bottom-right
    assert u1.size == (50, 50)
    assert u1.getpixel((10, 10)) == (255, 0, 0)        # red
    assert u2.getpixel((10, 10)) == (0, 255, 0)        # green
    assert u3.getpixel((10, 10)) == (0, 0, 255)        # blue
    assert u4.getpixel((10, 10)) == (255, 255, 255)    # white


def test_crop_quadrant_rejects_invalid(tmp_path: Path):
    import pytest
    src = _make_quadranted_grid(tmp_path)
    with pytest.raises(ValueError):
        crop_quadrant(src, 5)


# --------------- alpha_key_corners ---------------

def test_alpha_key_corners_keys_uniform_background():
    """A uniform mid-gray background with a high-contrast center should
    key the background to alpha=0 and leave the center opaque. The keyed
    ratio should be majority but not 100%."""
    clear()
    img = Image.new("RGB", (40, 40), (128, 128, 128))
    # Stamp a 10x10 hot-pink center
    for y in range(15, 25):
        for x in range(15, 25):
            img.putpixel((x, y), (255, 0, 255))
    keyed = alpha_key_corners(img)
    assert keyed.size == (40, 40)
    assert keyed.mode == "RGBA"
    # Corner is keyed
    assert keyed.getpixel((0, 0))[3] == 0
    # Center is opaque
    assert keyed.getpixel((20, 20))[3] == 255
    records = snapshot()
    assert records[-1]["tag"] == "ALPHA_KEY_APPLIED"
    p = records[-1]["payload"]
    assert p["tolerance"] == DEFAULT_TOLERANCE
    assert p["bg_r"] == 128 and p["bg_g"] == 128 and p["bg_b"] == 128
    assert p["total_count"] == 1600
    # Most of the background (1500 px) is keyed; the 100 center pixels are not.
    assert 1400 <= p["keyed_count"] <= 1550


def test_alpha_key_corners_respects_tolerance():
    """Tighter tolerance leaves more pixels opaque (when the background
    has any variance)."""
    img = Image.new("RGB", (20, 20), (128, 128, 128))
    # Introduce a noisy corner pixel
    img.putpixel((0, 0), (160, 160, 160))
    # tolerance=10 — corner average pulled high, fewer pixels match
    keyed_tight = alpha_key_corners(img, tolerance=10)
    # tolerance=80 — wide band, more pixels match
    keyed_wide = alpha_key_corners(img, tolerance=80)
    tight_alpha_sum = sum(keyed_tight.getpixel((x, y))[3] for x in range(20) for y in range(20))
    wide_alpha_sum = sum(keyed_wide.getpixel((x, y))[3] for x in range(20) for y in range(20))
    # Tighter tolerance -> more opaque pixels -> higher alpha sum
    assert tight_alpha_sum >= wide_alpha_sum


# --------------- promote ---------------

def test_promote_copies_file_and_emits(tmp_path: Path):
    clear()
    src = tmp_path / "src.png"
    src.write_bytes(b"\x89PNG\r\n\x1a\n" + b"x" * 100)
    dest = tmp_path / "deep" / "nested" / "dest.png"
    out = promote(src, dest)
    assert out == dest
    assert dest.exists()
    assert dest.read_bytes() == src.read_bytes()
    records = snapshot()
    assert len(records) == 1
    assert records[0]["tag"] == "ASSET_PROMOTED"
    p = records[0]["payload"]
    assert p["bytes"] == len(src.read_bytes())
    assert p["src"] == str(src)
    assert p["dest"] == str(dest)


def test_promote_creates_parents(tmp_path: Path):
    src = tmp_path / "a.png"
    src.write_bytes(b"abc")
    promote(src, tmp_path / "x" / "y" / "z" / "b.png")
    assert (tmp_path / "x" / "y" / "z" / "b.png").exists()


def test_promote_missing_src_raises(tmp_path: Path):
    import pytest
    with pytest.raises(FileNotFoundError):
        promote(tmp_path / "nope.png", tmp_path / "dest.png")

"""Behavior contract for ``cascade_img.curation.crop_grid``."""

from __future__ import annotations

from pathlib import Path

import pytest
from PIL import Image

from cascade_img.curation import crop_quadrant
from cascade_img.vocabulary import clear, snapshot


def _make_quadranted_grid(tmp_path: Path) -> Path:
    """100x100 image with four solid-color quadrants (TL=red, TR=green,
    BL=blue, BR=white). Used to verify each quadrant lands at the right
    output and isn't swapped with its neighbor."""
    img = Image.new("RGB", (100, 100), (0, 0, 0))
    for y in range(50):
        for x in range(50):
            img.putpixel((x, y), (255, 0, 0))               # TL red
            img.putpixel((x + 50, y), (0, 255, 0))          # TR green
            img.putpixel((x, y + 50), (0, 0, 255))          # BL blue
            img.putpixel((x + 50, y + 50), (255, 255, 255)) # BR white
    p = tmp_path / "grid.png"
    img.save(p)
    return p


def test_passthrough_emits_full_dims(tmp_path: Path):
    """quadrant=0 returns the whole image unchanged and emits w=full, h=full."""
    clear()
    src = _make_quadranted_grid(tmp_path)
    out = crop_quadrant(src, 0)
    assert out.size == (100, 100)
    records = snapshot()
    assert len(records) == 1
    assert records[0]["tag"] == "CROP_QUADRANT"
    assert records[0]["payload"] == {"quadrant": 0, "w": 100, "h": 100}


def test_returns_correct_quadrants(tmp_path: Path):
    """Each of U1..U4 returns the right corner color — proves the offsets
    aren't swapped (a swap was a real risk since the offsets are a dict literal)."""
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


def test_rejects_invalid_quadrant(tmp_path: Path):
    src = _make_quadranted_grid(tmp_path)
    with pytest.raises(ValueError):
        crop_quadrant(src, 5)


def test_releases_source_file_after_return(tmp_path: Path):
    """crop_quadrant called with a path must not hold a file descriptor on
    the source after returning — the source file may be deleted, moved, or
    overwritten by the consumer."""
    src = _make_quadranted_grid(tmp_path)
    out = crop_quadrant(src, 1)
    src.unlink()
    assert out.getpixel((10, 10)) == (255, 0, 0)


def test_zero_returns_copy_not_the_loader(tmp_path: Path):
    """quadrant=0 used to return the lazy PIL loader directly; now it returns
    a materialized copy so the consumer can outlive the source file."""
    src = _make_quadranted_grid(tmp_path)
    out = crop_quadrant(src, 0)
    src.unlink()
    assert out.size == (100, 100)
    assert out.getpixel((10, 10)) == (255, 0, 0)

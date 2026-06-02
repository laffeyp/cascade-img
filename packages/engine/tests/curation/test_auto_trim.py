"""Behavior contract for auto_trim: content bbox crop + the signal."""

from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from cascade_img.curation import auto_trim
from cascade_img.vocabulary import clear, snapshot


def test_alpha_mode_trims_to_opaque_extent(tmp_path):
    clear()
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    ImageDraw.Draw(img).rectangle((10, 10, 29, 29), fill=(255, 0, 0, 255))
    src = tmp_path / "s.png"
    img.save(src)
    dest = tmp_path / "t.png"

    auto_trim(src, dest, mode="alpha")
    with Image.open(dest) as res:
        assert res.size == (20, 20)
    rec = snapshot()[-1]
    assert rec["tag"] == "AUTO_TRIM_APPLIED"
    assert rec["payload"]["bbox"] == [10, 10, 30, 30]


def test_color_mode_trims_to_non_background(tmp_path):
    img = Image.new("RGB", (40, 40), (255, 255, 255))
    ImageDraw.Draw(img).rectangle((5, 5, 14, 14), fill=(0, 0, 0))
    src = tmp_path / "c.png"
    img.save(src)
    dest = tmp_path / "ct.png"

    auto_trim(src, dest, mode="color", tolerance=10)
    with Image.open(dest) as res:
        assert res.size == (10, 10)


def test_unknown_mode_raises(tmp_path):
    src = tmp_path / "x.png"
    Image.new("RGBA", (8, 8), (0, 0, 0, 255)).save(src)
    with pytest.raises(ValueError, match="unknown mode"):
        auto_trim(src, tmp_path / "o.png", mode="bogus")

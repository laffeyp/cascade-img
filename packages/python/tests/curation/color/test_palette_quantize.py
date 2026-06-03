"""Behavior contract for palette_quantize: palette reduction + the signal."""

from __future__ import annotations

import pytest
from PIL import Image

from cascade_img.curation import palette_quantize
from cascade_img.vocabulary import clear, snapshot


def _many_colors(tmp_path):
    img = Image.new("RGB", (32, 32))
    px = img.load()
    for y in range(32):
        for x in range(32):
            px[x, y] = ((x * 8) % 256, (y * 8) % 256, ((x + y) * 4) % 256)
    p = tmp_path / "g.png"
    img.save(p)
    return p


def test_quantize_reduces_color_count_and_emits_signal(tmp_path):
    clear()
    src = _many_colors(tmp_path)
    dest = tmp_path / "q.png"
    palette_quantize(src, dest, n_colors=8, method="median_cut")

    with Image.open(dest) as res:
        # getcolors returns one (count, color) entry per distinct color.
        assert len(res.convert("RGB").getcolors(maxcolors=256)) <= 8
    rec = snapshot()[-1]
    assert rec["tag"] == "PALETTE_QUANTIZED"
    assert rec["payload"]["n_colors"] == 8
    assert rec["payload"]["method"] == "median_cut"


def test_quantize_validates(tmp_path):
    src = tmp_path / "s.png"
    Image.new("RGB", (8, 8), (1, 2, 3)).save(src)
    with pytest.raises(ValueError, match="unknown method"):
        palette_quantize(src, tmp_path / "o.png", method="bogus")
    with pytest.raises(ValueError, match="2-256"):
        palette_quantize(src, tmp_path / "o.png", n_colors=1)

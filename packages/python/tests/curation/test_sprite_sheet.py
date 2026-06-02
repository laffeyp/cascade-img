"""Behavior contract for sprite_sheet: atlas + frame map + the signal."""

from __future__ import annotations

import json

import pytest
from PIL import Image

from cascade_img.curation import sprite_sheet
from cascade_img.vocabulary import clear, snapshot


def _sprites(tmp_path):
    srcs = []
    for i, c in enumerate([(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255)]):
        p = tmp_path / f"s{i}.png"
        Image.new("RGBA", (16, 16), c).save(p)
        srcs.append(p)
    return srcs


def test_row_layout_packs_atlas_and_frame_map(tmp_path):
    clear()
    srcs = _sprites(tmp_path)
    dest = tmp_path / "atlas.png"
    sprite_sheet(srcs, dest, layout="row")

    assert dest.exists()
    with Image.open(dest) as res:
        assert res.size == (48, 16)  # 3 across, one row, 16px cells

    map_p = dest.with_suffix(dest.suffix + ".frames.json")
    assert map_p.exists()
    frames = json.loads(map_p.read_text())["frames"]
    assert set(frames) == {"s0", "s1", "s2"}
    assert frames["s1"] == {"x": 16, "y": 0, "w": 16, "h": 16}

    rec = snapshot()[-1]
    assert rec["tag"] == "SPRITE_SHEET_PACKED"
    assert rec["payload"]["count"] == 3
    assert rec["payload"]["layout"] == "row"


def test_empty_srcs_raises(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        sprite_sheet([], tmp_path / "x.png")


def test_unknown_layout_raises(tmp_path):
    with pytest.raises(ValueError, match="unknown layout"):
        sprite_sheet([tmp_path / "a.png"], tmp_path / "x.png", layout="spiral")

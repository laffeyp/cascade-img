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


def test_same_stem_inputs_all_get_distinct_frames(tmp_path):
    """Two inputs sharing a stem (a cross-dir gather, re-rolls of one name) are
    placed into distinct cells but were keyed by stem — the second overwrote the
    first's frame entry, silently dropping a placed cell and making
    SPRITE_SHEET_PACKED count disagree with len(frames). Disambiguation gives
    every placed cell a distinct key. (review #2)"""
    clear()
    d1 = tmp_path / "a"
    d1.mkdir()
    d2 = tmp_path / "b"
    d2.mkdir()
    # Same stem "icon" in two dirs, different colors so the cells are distinct.
    p1 = d1 / "icon.png"
    Image.new("RGBA", (16, 16), (255, 0, 0, 255)).save(p1)
    p2 = d2 / "icon.png"
    Image.new("RGBA", (16, 16), (0, 255, 0, 255)).save(p2)
    dest = tmp_path / "atlas.png"
    sprite_sheet([p1, p2], dest, layout="row")

    frames = json.loads((dest.with_suffix(dest.suffix + ".frames.json")).read_text())["frames"]
    # Both cells survive as distinct entries at distinct x offsets.
    assert len(frames) == 2
    assert "icon" in frames and "icon_2" in frames
    assert frames["icon"]["x"] != frames["icon_2"]["x"]
    # The atlas is wide enough for both cells (no overlap).
    with Image.open(dest) as res:
        assert res.size == (32, 16)
    # The count signal matches the map size.
    rec = snapshot()[-1]
    assert rec["tag"] == "SPRITE_SHEET_PACKED"
    assert rec["payload"]["count"] == len(frames) == 2

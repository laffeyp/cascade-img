"""Behavior contract for contact_sheet: a labelled sheet on disk + the signal."""

from __future__ import annotations

from PIL import Image

from cascade_img.curation import contact_sheet
from cascade_img.vocabulary import clear, snapshot


def _grid(tmp_path, size=64):
    p = tmp_path / "grid.png"
    Image.new("RGBA", (size, size), (10, 20, 30, 255)).save(p)
    return p


def test_contact_sheet_writes_sheet_and_emits_signal(tmp_path):
    clear()
    src = _grid(tmp_path)
    dest = tmp_path / "sheet.png"
    out = contact_sheet(src, dest, labels=True)

    assert out == dest
    assert dest.exists()
    with Image.open(dest) as img:
        assert img.size == (64, 64)

    rec = snapshot()[-1]
    assert rec["tag"] == "CONTACT_SHEET_RENDERED"
    assert rec["payload"]["tiles"] == 4
    assert rec["payload"]["dest"] == str(dest)
    assert rec["payload"]["w"] == 64 and rec["payload"]["h"] == 64


def test_contact_sheet_labels_change_pixels(tmp_path):
    """labels=True draws badges, so the output differs from labels=False."""
    src = _grid(tmp_path)
    plain = contact_sheet(src, tmp_path / "plain.png", labels=False)
    labelled = contact_sheet(src, tmp_path / "labelled.png", labels=True)
    assert plain.read_bytes() != labelled.read_bytes()


def test_badge_does_not_punch_alpha_hole(tmp_path):
    """The translucent badge must be composited over the artwork, not written
    into the pixels — the saved sheet stays fully opaque under the badge."""
    src = tmp_path / "grid.png"
    Image.new("RGB", (100, 100), (40, 120, 200)).save(src)
    dest = tmp_path / "sheet.png"
    contact_sheet(src, dest)
    with Image.open(dest) as sheet:
        rgba = sheet.convert("RGBA")
        # Sample inside the slot-1 badge rectangle.
        assert rgba.getpixel((8, 8))[3] == 255

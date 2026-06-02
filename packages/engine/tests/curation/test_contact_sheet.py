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

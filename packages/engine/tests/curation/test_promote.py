"""Behavior contract for ``cascade_img.curation.promote``."""

from __future__ import annotations

from pathlib import Path

import pytest

from cascade_img.curation import promote
from cascade_img.vocabulary import clear, snapshot


def test_copies_file_and_emits_signal(tmp_path: Path):
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


def test_creates_parent_directories(tmp_path: Path):
    src = tmp_path / "a.png"
    src.write_bytes(b"abc")
    promote(src, tmp_path / "x" / "y" / "z" / "b.png")
    assert (tmp_path / "x" / "y" / "z" / "b.png").exists()


def test_missing_src_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        promote(tmp_path / "nope.png", tmp_path / "dest.png")

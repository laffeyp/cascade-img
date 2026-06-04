"""Hermetic tests for the capability-gallery image-property checks.

Proves the "is it animating / did it change / is it transparent" classifiers
work on constructed fixtures — so the gallery's automated assertions are
themselves trustworthy without a live render.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from PIL import Image

# tools/ isn't an importable package; load image_checks.py by path.
_TOOLS = Path(__file__).resolve().parents[2] / "tools" / "image_checks.py"
_spec = importlib.util.spec_from_file_location("image_checks", _TOOLS)
assert _spec and _spec.loader
image_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_checks)


def test_is_animated_detects_multiframe_webp(tmp_path: Path):
    p = tmp_path / "anim.webp"
    frames = [Image.new("RGB", (8, 8), (i * 80, 0, 0)) for i in range(3)]
    frames[0].save(p, save_all=True, append_images=frames[1:], format="WEBP", duration=100, loop=0)
    assert image_checks.is_animated(p) is True
    assert image_checks.frame_count(p) == 3


def test_still_image_is_not_animated(tmp_path: Path):
    p = tmp_path / "still.png"
    Image.new("RGB", (8, 8), (10, 20, 30)).save(p)
    assert image_checks.is_animated(p) is False
    assert image_checks.frame_count(p) == 1


def test_has_transparency(tmp_path: Path):
    keyed = tmp_path / "keyed.png"
    img = Image.new("RGBA", (10, 10), (255, 0, 0, 255))
    for x in range(10):  # punch a transparent column — 10% of the frame
        img.putpixel((x, 0), (0, 0, 0, 0))
    img.save(keyed)
    assert image_checks.has_transparency(keyed) is True

    opaque_rgb = tmp_path / "opaque.png"
    Image.new("RGB", (10, 10), (255, 0, 0)).save(opaque_rgb)
    assert image_checks.has_transparency(opaque_rgb) is False

    opaque_rgba = tmp_path / "opaque_rgba.png"
    Image.new("RGBA", (10, 10), (255, 0, 0, 255)).save(opaque_rgba)
    assert image_checks.has_transparency(opaque_rgba) is False


def test_images_differ(tmp_path: Path):
    black = tmp_path / "black.png"
    white = tmp_path / "white.png"
    black2 = tmp_path / "black2.png"
    Image.new("RGB", (16, 16), (0, 0, 0)).save(black)
    Image.new("RGB", (16, 16), (255, 255, 255)).save(white)
    Image.new("RGB", (16, 16), (0, 0, 0)).save(black2)

    assert image_checks.images_differ(black, white) is True
    assert image_checks.difference_fraction(black, white) == pytest.approx(1.0, abs=0.01)
    assert image_checks.images_differ(black, black2) is False
    assert image_checks.difference_fraction(black, black2) == pytest.approx(0.0, abs=0.001)

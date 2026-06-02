"""Behavior contract for the rembg alpha-key method.

rembg is an optional ([ml]) dependency. When absent, requesting it must raise a
clear install hint rather than an opaque ImportError. When present, the method
returns an RGBA image. Gated so the suite is green with or without the extra.
"""

from __future__ import annotations

import importlib.util

import pytest
from PIL import Image

from cascade_img.curation import alpha_key_corners

_HAS_REMBG = importlib.util.find_spec("rembg") is not None


@pytest.mark.skipif(_HAS_REMBG, reason="rembg installed; this asserts the missing-dep hint")
def test_missing_rembg_raises_install_hint():
    img = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
    with pytest.raises(RuntimeError, match=r"cascade-img\[ml\]"):
        alpha_key_corners(img, method="rembg")


@pytest.mark.skipif(not _HAS_REMBG, reason="rembg not installed (optional [ml] extra)")
def test_rembg_returns_rgba():
    img = Image.new("RGBA", (32, 32), (255, 255, 255, 255))
    out = alpha_key_corners(img, method="rembg")
    assert out.mode == "RGBA"
    assert out.size == (32, 32)

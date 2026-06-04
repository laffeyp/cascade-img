"""Cheap, dependency-light image-property checks for capability testing.

These are the "classifiers" the capability gallery (and any e2e that wants to
assert a real visual outcome) uses to answer questions like "did this actually
animate?" or "did this action change the image?" — without an ML model. Pure
Pillow; fast and deterministic.

- ``is_animated`` / ``frame_count`` — did ``animate_*`` produce a real animation?
- ``has_transparency`` — did ``alpha_key`` actually cut out a background?
- ``images_differ`` — did a param (``--exp``, ``--sw``, …) or an action
  (vary/zoom/pan) change the image, vs return something indistinguishable?

None of these judge *aesthetics* — only measurable properties. "Is this the
right subject / better art?" needs a human (the gallery writes images to a
folder for exactly that) or a real classifier (CLIP), which is out of scope here.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image


def frame_count(path: str | Path) -> int:
    """Number of frames in the image (1 for a still, >1 for an animation)."""
    with Image.open(path) as img:
        return int(getattr(img, "n_frames", 1))


def is_animated(path: str | Path) -> bool:
    """True if the file is a multi-frame animation (e.g. an ``animate_*`` WebP)."""
    with Image.open(path) as img:
        return bool(getattr(img, "is_animated", False)) or int(getattr(img, "n_frames", 1)) > 1


def has_transparency(path: str | Path, *, min_transparent_fraction: float = 0.01) -> bool:
    """True if the image has an alpha channel with a meaningful number of
    fully/partly transparent pixels — i.e. ``alpha_key`` actually keyed a
    background, rather than producing an opaque image with a dead alpha channel."""
    with Image.open(path) as img:
        if "A" not in img.getbands():
            return False
        alpha = img.convert("RGBA").getchannel("A")
        hist = alpha.histogram()  # 256 buckets, index == alpha value
        transparent = sum(hist[:255])  # anything not fully opaque
        total = sum(hist) or 1
        return (transparent / total) >= min_transparent_fraction


def difference_fraction(path_a: str | Path, path_b: str | Path, *, size: int = 32) -> float:
    """Mean normalized per-pixel difference (0.0 identical … 1.0 opposite),
    computed on a downscaled grayscale copy so it's robust to size/format and
    cheap. A small grid is enough to tell "changed" from "unchanged"."""
    with Image.open(path_a) as a_img, Image.open(path_b) as b_img:
        a = a_img.convert("L").resize((size, size))
        b = b_img.convert("L").resize((size, size))
    a_px = a.tobytes()  # one byte per pixel for an "L" image; not deprecated
    b_px = b.tobytes()
    total = sum(abs(x - y) for x, y in zip(a_px, b_px, strict=True))
    return total / (len(a_px) * 255)


def images_differ(path_a: str | Path, path_b: str | Path, *, min_fraction: float = 0.02) -> bool:
    """True if two images differ by more than ``min_fraction`` (default 2%) of
    full-scale brightness, averaged per pixel. Use to confirm a param or action
    actually changed the output instead of returning a near-duplicate."""
    return difference_fraction(path_a, path_b) >= min_fraction

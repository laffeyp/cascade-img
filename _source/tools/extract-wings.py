#!/usr/bin/env python3.11
"""
Sprint 4.7d — Extract wings-only sprites by subtracting the canonical
body silhouette from MJ-generated wing-frame images.

MJ refuses to produce wings-without-bodies (oref pulls toward the
canonical bird identity). Workaround: use the canonical assets/bird.png
as a body-mask. Wherever the canonical bird has opaque pixels, set the
wing-frame's alpha to 0. Whatever opaque pixels remain in the wing-frame
are the WINGS that extend beyond the body silhouette.

Usage:
    python3 tools/extract-wings.py

Reads:
    assets/bird.png                                  (body mask)
    Cascade/asset_pipeline/generated/wing_only_*.png (body + wing)

Writes:
    assets/bird/wing_only_{up,mid,down}.png          (wing-only RGBA)

Note: the body in the wing-frame may sit at a slightly different
position/scale than the canonical. The script dilates the mask by
DILATE_PX to absorb that offset. If wings get over-cropped, lower
DILATE_PX. If body leak persists, raise it.
"""

import sys
from pathlib import Path
from PIL import Image, ImageFilter

ROOT = Path(__file__).parent.parent
CANONICAL = ROOT / "assets" / "bird.png"
# Reads alpha-keyed inputs from assets/bird/ (which crop-grid.py wrote).
# Overwrites them in place with wings-only RGBA.
SRC_DIR = ROOT / "assets" / "bird"
OUT_DIR = ROOT / "assets" / "bird"

# Dilation radius for the body mask. Larger = body silhouette grows
# outward more, eating into wing edges that touch the body. Smaller
# = body leaks through if wing-frame body isn't perfectly aligned.
DILATE_PX = 8

# Alpha threshold for "this pixel is body" — pixels with alpha above
# this value in the canonical bird get masked out of the wing frame.
BODY_ALPHA_THRESHOLD = 64


def centroid_of_alpha(img: Image.Image) -> tuple[int, int]:
    """Return centroid (x, y) of opaque pixels in an RGBA image."""
    _, _, _, a = img.split()
    a_data = a.load()
    w, h = img.size
    total = 0
    sx = sy = 0
    for y in range(h):
        for x in range(w):
            if a_data[x, y] > BODY_ALPHA_THRESHOLD:
                total += 1
                sx += x
                sy += y
    if total == 0:
        return w // 2, h // 2
    return sx // total, sy // total


def extract(canonical_path: Path, wingframe_path: Path, out_path: Path) -> None:
    canonical = Image.open(canonical_path).convert("RGBA")
    wingframe = Image.open(wingframe_path).convert("RGBA")

    # Align sizes if they differ (MJ outputs vary between 1024 and 2048).
    if canonical.size != wingframe.size:
        canonical = canonical.resize(wingframe.size, Image.LANCZOS)

    # Auto-align canonical to the wing-frame: shift canonical so its
    # centroid matches the wing-frame's centroid. The bird body in the
    # wing-frame sits wherever MJ placed it; the canonical needs to
    # be moved to overlay correctly before we use its mask.
    cx_can, cy_can = centroid_of_alpha(canonical)
    cx_wing, cy_wing = centroid_of_alpha(wingframe)
    dx, dy = cx_wing - cx_can, cy_wing - cy_can
    if dx != 0 or dy != 0:
        shifted = Image.new("RGBA", canonical.size, (0, 0, 0, 0))
        shifted.paste(canonical, (dx, dy))
        canonical = shifted
        print(f"  centroid shift dx={dx} dy={dy}")

    # Build a body mask from the (aligned) canonical alpha channel.
    _, _, _, body_alpha = canonical.split()
    # Threshold + dilate
    body_mask = body_alpha.point(lambda a: 255 if a > BODY_ALPHA_THRESHOLD else 0)
    body_mask = body_mask.filter(ImageFilter.MaxFilter(DILATE_PX * 2 + 1))

    # Apply the inverse mask to the wing-frame: where the body is opaque,
    # the wing-frame becomes transparent. Where the body is transparent,
    # the wing-frame keeps its original alpha.
    wr, wg, wb, wa = wingframe.split()
    # new_alpha = wa where body_mask == 0; else 0.
    body_mask_data = body_mask.load()
    wa_data = wa.load()
    w, h = wingframe.size
    new_alpha = Image.new("L", (w, h), 0)
    new_alpha_data = new_alpha.load()
    for y in range(h):
        for x in range(w):
            if body_mask_data[x, y] == 0:
                new_alpha_data[x, y] = wa_data[x, y]
    out = Image.merge("RGBA", (wr, wg, wb, new_alpha))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out.save(out_path)
    print(f"[extract] {wingframe_path.name} -> {out_path}")


def main() -> int:
    if not CANONICAL.exists():
        print(f"canonical not found: {CANONICAL}", file=sys.stderr)
        return 1
    for name in ["up", "mid", "down"]:
        src = SRC_DIR / f"wing_only_{name}.png"
        if not src.exists():
            print(f"skip (not found): {src}", file=sys.stderr)
            continue
        out = OUT_DIR / f"wing_only_{name}.png"
        extract(CANONICAL, src, out)
    return 0


if __name__ == "__main__":
    sys.exit(main())

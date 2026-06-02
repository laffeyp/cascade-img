#!/usr/bin/env python3.11
"""
Sprint 4.7e — Extract canonical bird's head + feet as separate overlay
sprites. PlayerBird Container layers these on top of the swapping body
during flit, so head/eyes/feet stay locked even as the body sprite
transitions between wing-positions.

Heuristic: bird is centered in the 1024×1024 canvas, oriented side-view.
Head occupies the top ~30% of the visible bbox; feet the bottom ~12%.
Crop these vertical bands from the canonical bird and save as separate
RGBA PNGs.

Usage:
    python3 tools/extract-head-feet.py
"""

import sys
from pathlib import Path
from PIL import Image

ROOT = Path(__file__).parent.parent
CANONICAL = ROOT / "assets" / "bird.png"
OUT_DIR = ROOT / "assets" / "bird"

# Vertical bands as proportions of the visible bird bbox (NOT the canvas).
HEAD_TOP = 0.0
HEAD_BOTTOM = 0.42   # top 42% = head + cap + beak
FEET_TOP = 0.85      # bottom 15% = feet + base
FEET_BOTTOM = 1.0


def opaque_bbox(img: Image.Image, alpha_thresh: int = 32) -> tuple[int, int, int, int]:
    _, _, _, a = img.split()
    px = a.load()
    w, h = img.size
    minx, miny, maxx, maxy = w, h, 0, 0
    for y in range(h):
        for x in range(w):
            if px[x, y] > alpha_thresh:
                if x < minx: minx = x
                if y < miny: miny = y
                if x > maxx: maxx = x
                if y > maxy: maxy = y
    return minx, miny, maxx, maxy


def main() -> int:
    if not CANONICAL.exists():
        print(f"canonical not found: {CANONICAL}", file=sys.stderr)
        return 1
    bird = Image.open(CANONICAL).convert("RGBA")
    w, h = bird.size
    bx, by, bxx, byy = opaque_bbox(bird)
    bh = byy - by
    print(f"canonical bbox: x={bx}-{bxx} y={by}-{byy}  body height={bh}")

    # Head band: vertical slice of the bird's bbox.
    head_top = by + int(bh * HEAD_TOP)
    head_bot = by + int(bh * HEAD_BOTTOM)
    head = bird.crop((bx, head_top, bxx, head_bot))
    # Save with full canvas size for easy compositing — head positioned
    # at the right place when overlaid on a same-size canvas.
    head_full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    head_full.paste(head, (bx, head_top))
    head_full.save(OUT_DIR / "head.png")
    print(f"  head -> assets/bird/head.png  band y={head_top}-{head_bot} ({head.size[0]}x{head.size[1]})")

    feet_top_y = by + int(bh * FEET_TOP)
    feet_bot_y = by + int(bh * FEET_BOTTOM)
    feet = bird.crop((bx, feet_top_y, bxx, feet_bot_y))
    feet_full = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    feet_full.paste(feet, (bx, feet_top_y))
    feet_full.save(OUT_DIR / "feet.png")
    print(f"  feet -> assets/bird/feet.png  band y={feet_top_y}-{feet_bot_y} ({feet.size[0]}x{feet.size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

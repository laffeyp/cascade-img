#!/usr/bin/env python3.11
"""
Sprint 4.0 — Grid quadrant cropper + promoter.

Usage:
    python3 tools/crop-grid.py <asset_id> <quadrant>

Where:
    asset_id  = bird | clue_a | clue_b | clue_c | region_forest_floor
    quadrant  = 1 | 2 | 3 | 4   (MJ's U1/U2/U3/U4 layout: TL, TR, BL, BR)

Reads:
    Cascade/asset_pipeline/generated/<asset_id>.webp

Writes:
    Katybird/assets/<destination>/<asset_id>.png

Promotion table (matches Sprint 4.0 card asset layout):
    bird                 -> assets/bird.png
    clue_a/b/c           -> assets/clues/<id>.png
    region_forest_floor  -> assets/regions/forest_floor.png
"""

import sys
from pathlib import Path
from PIL import Image

CASCADE_GENERATED = Path("/Users/<user>/Documents/Claude/Projects/Cascade/asset_pipeline/generated")
KATYBIRD_ASSETS = Path("/Users/<user>/Documents/Claude/Projects/Katybird/assets")

PROMOTION = {
    "bird": "bird.png",
    "clue_a": "clues/clue_a.png",
    "clue_b": "clues/clue_b.png",
    "clue_c": "clues/clue_c.png",
    "region_forest_floor": "regions/forest_floor.png",
    # Phase 4.5 — Wave-3 region panels (same look as forest_floor)
    "region_forest_a": "regions/forest_a.png",
    "region_forest_b": "regions/forest_b.png",
    "region_forest_c": "regions/forest_c.png",
    "region_forest_rain": "regions/forest_rain.png",
    # Wave 2
    "glyph_surface_action": "hud/glyph_surface_action.png",
    "glyph_recognized_pattern": "hud/glyph_recognized_pattern.png",
    "glyph_recognized_wound": "hud/glyph_recognized_wound.png",
    "glyph_specific_repair": "hud/glyph_specific_repair.png",
    "katy_silhouette": "katy/katy_silhouette.png",
    "katy_movement": "katy/katy_movement.png",
    "katy_direct_sighting": "katy/katy_direct_sighting.png",
    # Sprint 4.7: flit wing-flap frames
    "bird_wing_up": "bird/wing_up.png",
    "bird_wing_mid": "bird/wing_mid.png",
    "bird_wing_down": "bird/wing_down.png",
    # Sprint 4.7d: wings-only overlay (body stays locked)
    "wing_only_up": "bird/wing_only_up.png",
    "wing_only_mid": "bird/wing_only_mid.png",
    "wing_only_down": "bird/wing_only_down.png",
}

# MJ frequently ignores "transparent background" in the prompt and ships
# the sprite on a near-uniform colored backdrop. For character / item
# sprites we want alpha — for full-scene regions we want the backdrop.
ALPHA_KEY = {
    "bird": True,
    "clue_a": True,
    "clue_b": True,
    "clue_c": True,
    "region_forest_floor": False,
    "region_forest_a": False,
    "region_forest_b": False,
    "region_forest_c": False,
    "region_forest_rain": False,
    # Wave 2 — all character/item-class sprites want transparency.
    "glyph_surface_action": True,
    "glyph_recognized_pattern": True,
    "glyph_recognized_wound": True,
    "glyph_specific_repair": True,
    "katy_silhouette": True,
    "katy_movement": True,
    "katy_direct_sighting": True,
    # Sprint 4.7: flit wing-flap frames
    "bird_wing_up": True,
    "bird_wing_mid": True,
    "bird_wing_down": True,
    "wing_only_up": True,
    "wing_only_mid": True,
    "wing_only_down": True,
}

# Alpha-key tolerance — how close to the sampled background color a pixel
# must be (per-channel) to be made transparent. Tuned for MJ's sprite art
# which has soft anti-aliased edges; too tight leaves a halo, too loose
# eats into the sprite. 40 (0-255) is a reasonable starting point.
ALPHA_KEY_TOLERANCE = 40

# MJ grid layout (top-left origin, U1..U4):
#   U1 U2
#   U3 U4
QUADRANT_OFFSETS = {
    1: (0, 0),  # top-left
    2: (1, 0),  # top-right
    3: (0, 1),  # bottom-left
    4: (1, 1),  # bottom-right
}


def crop_quadrant(src: Path, quadrant: int) -> Image.Image:
    """Quadrant 0 = whole image (single upscale, no crop). 1-4 = grid quadrant."""
    img = Image.open(src)
    if quadrant == 0:
        return img
    w, h = img.size
    qw, qh = w // 2, h // 2
    fx, fy = QUADRANT_OFFSETS[quadrant]
    box = (fx * qw, fy * qh, fx * qw + qw, fy * qh + qh)
    return img.crop(box)


def alpha_key_corners(img: Image.Image, tolerance: int = ALPHA_KEY_TOLERANCE) -> Image.Image:
    """Sample the four corner pixels, average them to get the background
    color, then set alpha=0 on every pixel within `tolerance` per channel.

    Assumes sprite-style art: subject centered, near-uniform backdrop.
    Not appropriate for full-scene region backdrops."""
    rgba = img.convert("RGBA")
    w, h = rgba.size
    px = rgba.load()
    if px is None:
        return rgba

    # Sample 4 corners; average gives a stable bg color even with light
    # JPEG-style compression noise on the MJ output.
    corners = [px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]]
    bg_r = sum(c[0] for c in corners) // 4
    bg_g = sum(c[1] for c in corners) // 4
    bg_b = sum(c[2] for c in corners) // 4

    keyed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, _a = px[x, y]
            if (
                abs(r - bg_r) <= tolerance
                and abs(g - bg_g) <= tolerance
                and abs(b - bg_b) <= tolerance
            ):
                px[x, y] = (r, g, b, 0)
                keyed += 1
    pct = (keyed / (w * h)) * 100 if w * h else 0
    print(f"[crop] alpha-keyed {keyed}/{w*h} px ({pct:.1f}%), bg=({bg_r},{bg_g},{bg_b})")
    return rgba


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    asset_id = sys.argv[1]
    try:
        quadrant = int(sys.argv[2])
    except ValueError:
        print(f"quadrant must be 0 (whole) or 1-4 (got {sys.argv[2]})", file=sys.stderr)
        return 2
    if quadrant != 0 and quadrant not in QUADRANT_OFFSETS:
        print(f"quadrant must be 0 (whole) or 1-4 (got {quadrant})", file=sys.stderr)
        return 2
    if asset_id not in PROMOTION:
        print(f"unknown asset_id {asset_id!r}; one of: {', '.join(PROMOTION)}", file=sys.stderr)
        return 2

    # Upscale outputs land as <asset_id>.png; grid-only outputs land as
    # <asset_id>.webp. Try both.
    src = CASCADE_GENERATED / f"{asset_id}.png"
    if not src.exists():
        src = CASCADE_GENERATED / f"{asset_id}.webp"
    if not src.exists():
        print(f"source not found: {asset_id}.png or {asset_id}.webp in {CASCADE_GENERATED}", file=sys.stderr)
        return 1

    cropped = crop_quadrant(src, quadrant)

    if ALPHA_KEY.get(asset_id, False):
        cropped = alpha_key_corners(cropped)

    dst = KATYBIRD_ASSETS / PROMOTION[asset_id]
    dst.parent.mkdir(parents=True, exist_ok=True)
    cropped.save(dst, format="PNG")

    print(f"[crop] {asset_id} U{quadrant}: {src.name} -> {dst}")
    print(f"[crop] size: {cropped.size[0]}x{cropped.size[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

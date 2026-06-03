"""Corner-anchored alpha keyer for sprite-style outputs.

Two algorithms share the same entry point:

``method="flood"`` (default) — flood-fills from the four corners using PIL's
4-connected flood-fill: a pixel is keyed when its L1 colour distance from the
corner seed is within ``tolerance``. Only pixels reachable from a corner by a
path of colour-similar neighbours are keyed.
Subject regions whose color is close to the background but are surrounded by
a darker outline (a white penguin belly inside a black outline on a white
background) stay opaque because the outline blocks the flood. This is the
correct algorithm for most MJ illustration outputs.

``method="threshold"`` — the original global-threshold algorithm: keys every
pixel within ``tolerance`` per channel of the corner-average color regardless
of position. Faster and simpler, but eats subject pixels that happen to be
close to the background color. Kept for backward compatibility and for
domains where flood-fill leaks (e.g. broken outlines, intentional gradients
from bg into subject).

``method="rembg"`` — ML background removal via the optional ``rembg``
dependency (the ``[ml]`` extra). Handles the gradient, vignette, textured, and
broken-outline cases where both corner-anchored algorithms fail. Lazy-imported;
raises a clear install hint if the extra is absent.

None of these are appropriate for full-scene images where the frame IS
the asset; apply selectively per asset in the consumer's curation flow.
"""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageDraw

from cascade_img.curation._shared import _pixels, _rgba_components, _sample_bg
from cascade_img.vocabulary import emit

DEFAULT_TOLERANCE = 40

# Sentinel color used to mark flood-filled pixels in the working RGB copy.
# Picked outside the typical illustration palette; the keyer falls back to a
# pixel-by-pixel comparison if the source image already contains this color.
_FLOOD_SENTINEL = (255, 0, 255)


def _alpha_key_threshold(rgba: Image.Image, tolerance: int) -> tuple[Image.Image, int]:
    """Global-threshold keyer. Returns (image, keyed_count)."""
    bg_r, bg_g, bg_b = _sample_bg(rgba)
    px = _pixels(rgba)
    w, h = rgba.size
    keyed = 0
    for y in range(h):
        for x in range(w):
            r, g, b, _a = _rgba_components(px[x, y], rgba.mode)
            if (
                abs(r - bg_r) <= tolerance
                and abs(g - bg_g) <= tolerance
                and abs(b - bg_b) <= tolerance
            ):
                px[x, y] = (r, g, b, 0)
                keyed += 1
    return rgba, keyed


def _color_l1(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    """L1 (sum-of-absolute-per-channel) RGB distance — the same metric PIL's
    ImageDraw.floodfill uses for its ``thresh`` comparison."""
    return abs(a[0] - b[0]) + abs(a[1] - b[1]) + abs(a[2] - b[2])


def _flood_from_corners_bfs(rgb: Image.Image, tolerance: int) -> set[tuple[int, int]]:
    """Pure-Python flood-fill from the four corners, **matching PIL's
    ImageDraw.floodfill semantics** so the fallback keys identically to the fast
    path: from each corner's seed pixel, a 4-connected pixel joins the
    background when its L1 colour distance from THAT seed is <= ``tolerance``.

    Used only when the source already contains the flood sentinel colour (so the
    sentinel-mark fast path would mis-classify). Returns the background coords.
    Previously this compared each pixel to the corner-*average* with a
    per-channel test — a different metric and anchor than the fast path, so the
    same image keyed differently depending on which path ran (now fixed)."""
    w, h = rgb.size
    px = _pixels(rgb)
    background: set[tuple[int, int]] = set()
    for sx, sy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        seed = px[sx, sy][:3]
        enqueued = {(sx, sy)}
        queue: deque[tuple[int, int]] = deque([(sx, sy)])
        while queue:
            x, y = queue.popleft()
            if _color_l1(px[x, y][:3], seed) > tolerance:
                continue  # a wall (outside tolerance of this seed) — not background
            background.add((x, y))
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in enqueued:
                    enqueued.add((nx, ny))
                    queue.append((nx, ny))
    return background


def _alpha_key_flood(rgba: Image.Image, tolerance: int) -> tuple[Image.Image, int]:
    """Flood-fill keyer. Returns (image, keyed_count).

    Floods from each corner using PIL.ImageDraw.floodfill with a sentinel
    color and per-channel tolerance. Subject regions surrounded by a darker
    outline stay opaque because the outline blocks the flood. Falls back to a
    pure-Python BFS if the source image already contains the sentinel color.
    """
    w, h = rgba.size
    rgb_work = rgba.convert("RGB").copy()

    # ImageDraw.floodfill marks reachable pixels with _FLOOD_SENTINEL; the
    # follow-up pass writes alpha=0 wherever the working image is sentinel.
    # If the source already contains the sentinel color, the follow-up would
    # mis-classify those pixels — fall back to the pure-Python BFS, which
    # tracks visited coordinates directly and doesn't need a color sentinel.
    palette = rgb_work.getcolors(maxcolors=w * h)
    if palette is None:
        # Image has more unique colors than `getcolors` will count; do a
        # direct scan via getdata().
        use_bfs = _FLOOD_SENTINEL in set(rgb_work.getdata())
    else:
        use_bfs = any(color == _FLOOD_SENTINEL for _count, color in palette)

    if use_bfs:
        bg_coords = _flood_from_corners_bfs(rgb_work, tolerance)
        px = _pixels(rgba)
        keyed = 0
        for x, y in bg_coords:
            r, g, b, _ = _rgba_components(px[x, y], rgba.mode)
            px[x, y] = (r, g, b, 0)
            keyed += 1
        return rgba, keyed

    # PIL fast path: ImageDraw.floodfill marks reachable bg pixels with the
    # sentinel; a follow-up pass writes alpha=0 where the work image is
    # sentinel and leaves opaque pixels untouched.
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        ImageDraw.floodfill(rgb_work, xy, _FLOOD_SENTINEL, thresh=tolerance)

    src = _pixels(rgba)
    work = _pixels(rgb_work)
    keyed = 0
    for y in range(h):
        for x in range(w):
            if work[x, y] == _FLOOD_SENTINEL:
                r, g, b, _ = _rgba_components(src[x, y], rgba.mode)
                src[x, y] = (r, g, b, 0)
                keyed += 1
    return rgba, keyed


def _alpha_key_rembg(rgba: Image.Image) -> tuple[Image.Image, int]:
    """ML background removal via the optional ``rembg`` dependency.

    The corner-anchored algorithms fail on gradient/vignette/textured
    backgrounds and broken outlines; rembg's learned matting handles those.
    Requires the optional ``[ml]`` extra (``pip install 'cascade-img[ml]'``),
    which pulls onnxruntime (~150 MB). Returns (image, keyed_count).
    """
    try:
        from rembg import remove
    except ImportError as e:
        raise RuntimeError(
            "alpha_key_corners(method='rembg') needs the optional 'rembg' "
            "dependency. Install it with: pip install 'cascade-img[ml]' "
            "(pulls onnxruntime, ~150 MB)."
        ) from e
    out = remove(rgba).convert("RGBA")
    keyed = out.getchannel("A").histogram()[0]
    return out, keyed


def alpha_key_corners(
    img: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    method: str = "flood",
) -> Image.Image:
    """Apply corner-anchored alpha keying.

    Args:
        img: PIL Image (any mode; converted to RGBA internally).
        tolerance: For flood mode, the maximum L1 colour distance (sum of the
            per-channel absolute differences) a pixel may be from a corner's
            seed colour to be flooded as background — PIL's connected
            flood-fill, matched by the BFS fallback. For threshold mode, the
            per-channel band around the corner-average color that counts as
            background.
        method: ``"flood"`` (default; corner-anchored 4-connected flood-fill),
            ``"threshold"`` (global per-pixel distance check), or ``"rembg"``
            (ML background removal; needs the ``[ml]`` extra). ``tolerance`` is
            ignored for ``"rembg"``.

    Returns:
        RGBA Image with background pixels set to alpha=0.
    """
    rgba = img.convert("RGBA")
    w, h = rgba.size
    if rgba.load() is None or w == 0 or h == 0:
        return rgba

    bg_r, bg_g, bg_b = _sample_bg(rgba)

    if method == "flood":
        rgba, keyed = _alpha_key_flood(rgba, tolerance)
    elif method == "threshold":
        rgba, keyed = _alpha_key_threshold(rgba, tolerance)
    elif method == "rembg":
        rgba, keyed = _alpha_key_rembg(rgba)
        w, h = rgba.size
    else:
        raise ValueError(
            f"alpha_key_corners: unknown method {method!r}; expected 'flood', "
            f"'threshold', or 'rembg'."
        )

    total = w * h
    emit(
        "ALPHA_KEY_APPLIED",
        tolerance=tolerance,
        bg_r=bg_r,
        bg_g=bg_g,
        bg_b=bg_b,
        keyed_count=keyed,
        total_count=total,
    )
    return rgba

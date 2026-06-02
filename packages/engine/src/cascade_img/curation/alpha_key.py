"""Corner-anchored alpha keyer for sprite-style outputs.

Two algorithms share the same entry point:

``method="flood"`` (default) — flood-fills from the four corners using PIL's
4-connected flood-fill with a per-channel tolerance threshold. Only pixels
reachable from a corner by a path of color-similar neighbors are keyed.
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

Neither algorithm is appropriate for full-scene images where the frame IS
the asset; apply selectively per asset in the consumer's curation flow.
"""

from __future__ import annotations

from collections import deque

from PIL import Image, ImageDraw

from cascade_img.vocabulary import emit

DEFAULT_TOLERANCE = 40

# Sentinel color used to mark flood-filled pixels in the working RGB copy.
# Picked outside the typical illustration palette; the keyer falls back to a
# pixel-by-pixel comparison if the source image already contains this color.
_FLOOD_SENTINEL = (255, 0, 255)


def _rgba_components(pixel, mode: str) -> tuple[int, int, int, int]:
    """Normalize PIL pixel-access output to (r, g, b, a).

    ``convert("RGBA")`` is well-defined for ordinary inputs but some modes
    (P with single-channel transparency, corrupt files) yield 3-channel
    tuples. Tolerate >=3 channels; default alpha to 255 when absent.
    """
    if len(pixel) >= 4:
        return pixel[0], pixel[1], pixel[2], pixel[3]
    if len(pixel) == 3:
        return pixel[0], pixel[1], pixel[2], 255
    raise ValueError(
        f"alpha_key_corners: pixel access returned {len(pixel)}-channel data; "
        f"image mode={mode!r}; expected RGB or RGBA after convert('RGBA')."
    )


def _sample_bg(rgba: Image.Image) -> tuple[int, int, int]:
    """Four-corner-average background color in 0-255 RGB space."""
    px = rgba.load()
    w, h = rgba.size
    corners = (px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1])
    rs = [_rgba_components(c, rgba.mode) for c in corners]
    return (
        sum(c[0] for c in rs) // 4,
        sum(c[1] for c in rs) // 4,
        sum(c[2] for c in rs) // 4,
    )


def _alpha_key_threshold(rgba: Image.Image, tolerance: int) -> tuple[Image.Image, int]:
    """Global-threshold keyer. Returns (image, keyed_count)."""
    bg_r, bg_g, bg_b = _sample_bg(rgba)
    px = rgba.load()
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


def _flood_from_corners_bfs(rgb: Image.Image, tolerance: int) -> set[tuple[int, int]]:
    """Pure-Python BFS flood-fill from the four corners.

    Used as a fallback when PIL's ImageDraw.floodfill collides with the
    sentinel (the source image already contains the sentinel color). Returns
    the set of (x, y) coordinates classified as background.
    """
    w, h = rgb.size
    px = rgb.load()
    bg_r, bg_g, bg_b = _sample_bg(rgb.convert("RGBA"))
    visited: set[tuple[int, int]] = set()
    queue: deque[tuple[int, int]] = deque()
    for xy in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        queue.append(xy)
        visited.add(xy)
    while queue:
        x, y = queue.popleft()
        r, g, b = px[x, y][:3]
        if abs(r - bg_r) > tolerance or abs(g - bg_g) > tolerance or abs(b - bg_b) > tolerance:
            visited.discard((x, y))
            continue
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h and (nx, ny) not in visited:
                visited.add((nx, ny))
                queue.append((nx, ny))
    return visited


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
        px = rgba.load()
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

    src = rgba.load()
    work = rgb_work.load()
    keyed = 0
    for y in range(h):
        for x in range(w):
            if work[x, y] == _FLOOD_SENTINEL:
                r, g, b, _ = _rgba_components(src[x, y], rgba.mode)
                src[x, y] = (r, g, b, 0)
                keyed += 1
    return rgba, keyed


def alpha_key_corners(
    img: Image.Image,
    tolerance: int = DEFAULT_TOLERANCE,
    method: str = "flood",
) -> Image.Image:
    """Apply corner-anchored alpha keying.

    Args:
        img: PIL Image (any mode; converted to RGBA internally).
        tolerance: Per-channel tolerance band around the sampled background.
            For flood mode, the maximum per-channel step the flood will
            tolerate between neighbors. For threshold mode, the global
            distance from the corner-average color that counts as background.
        method: ``"flood"`` (default; corner-anchored 4-connected flood-fill)
            or ``"threshold"`` (global per-pixel distance check).

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
    else:
        raise ValueError(
            f"alpha_key_corners: unknown method {method!r}; expected 'flood' or 'threshold'."
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

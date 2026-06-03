"""MCP tools for the post-generation curation steps.

Thin wrappers over :mod:`cascade_img.curation`: crop, alpha-key, trim,
quantize, sheet assembly, scoring, and promotion. The curation functions are
imported under ``curation_*`` aliases so they don't shadow the same-named tool
functions exposed here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from cascade_img.curation import (
    DEFAULT_TOLERANCE,
    alpha_key_corners,
    crop_quadrant,
)
from cascade_img.curation import auto_trim as curation_auto_trim
from cascade_img.curation import contact_sheet as curation_contact_sheet
from cascade_img.curation import palette_quantize as curation_palette_quantize
from cascade_img.curation import promote as curation_promote
from cascade_img.curation import score_grid as curation_score_grid
from cascade_img.curation import sprite_sheet as curation_sprite_sheet
from cascade_img.interfaces.mcp import _envelope


async def crop_grid(
    src: str,
    quadrant: int,
    dest: str | None = None,
) -> dict[str, Any]:
    """Crop one quadrant of an MJ grid. ``quadrant=0`` returns the whole
    image. If ``dest`` is set, write the cropped image to that path."""

    def go():
        img = crop_quadrant(src, quadrant)
        out: dict[str, Any] = {"w": img.size[0], "h": img.size[1]}
        if dest:
            Path(dest).parent.mkdir(parents=True, exist_ok=True)
            img.save(dest)
            out["dest"] = dest
        return out

    return await _envelope._run_tool("crop_grid", go)


async def alpha_key(
    src: str,
    dest: str,
    tolerance: int = DEFAULT_TOLERANCE,
    method: str = "flood",
) -> dict[str, Any]:
    """Apply corner-anchored alpha keying. Reads ``src``, writes RGBA to ``dest``.

    ``method`` is ``"flood"`` (default — 4-connected flood-fill from each
    corner; correct for sprite-on-uniform-bg cases where the subject has a
    darker outline), ``"threshold"`` (per-pixel distance from corner-average;
    faster but eats subject pixels whose color is close to the background), or
    ``"rembg"`` (ML background removal for gradient/vignette/textured
    backgrounds; needs the optional ``[ml]`` extra).

    The returned ``keyed_ratio`` is the fraction of pixels keyed transparent
    (0.0-1.0). The agent can use it to detect failure: typical sprite outputs
    key 0.4-0.8 of the frame; ratios <0.1 mean the keyer didn't find the
    background (gradient/vignette/wrong tolerance); ratios >0.9 mean the keyer
    ate the subject and the result should be rejected or re-rolled.
    """
    from PIL import Image

    def go():
        # Close the source loader explicitly so long-running MCP servers
        # don't exhaust file descriptors.
        with Image.open(src) as img:
            keyed = alpha_key_corners(img, tolerance=tolerance, method=method)
        Path(dest).parent.mkdir(parents=True, exist_ok=True)
        keyed.save(dest)
        # Count alpha=0 pixels via the alpha channel's histogram; bucket 0
        # is fully transparent. Cheaper than a Python pixel walk.
        keyed_count = keyed.getchannel("A").histogram()[0]
        total = keyed.size[0] * keyed.size[1]
        return {
            "dest": dest,
            "w": keyed.size[0],
            "h": keyed.size[1],
            "method": method,
            "tolerance": tolerance,
            "keyed_count": keyed_count,
            "total_count": total,
            "keyed_ratio": round(keyed_count / total, 4) if total else 0.0,
        }

    return await _envelope._run_tool("alpha_key", go)


async def promote(src: str, dest: str) -> dict[str, Any]:
    """Copy a curated asset from staging into the consumer's asset tree."""

    def go():
        out = curation_promote(src, dest)
        return {"dest": str(out)}

    return await _envelope._run_tool("promote", go)


async def contact_sheet(src: str, dest: str, labels: bool = True) -> dict[str, Any]:
    """Composite a 2x2 grid into one labelled contact sheet for vision-model
    selection. ``src`` is the grid; the 1-4 index badge is drawn on each panel
    unless ``labels`` is false. Returns ``{ok, result: {dest}}``."""

    def go():
        out = curation_contact_sheet(src, dest, labels=labels)
        return {"dest": str(out)}

    return await _envelope._run_tool("contact_sheet", go)


async def auto_trim(
    src: str,
    dest: str,
    mode: str = "alpha",
    tolerance: int = 10,
) -> dict[str, Any]:
    """Crop an image to its content bounding box. ``mode`` is ``"alpha"``
    (non-transparent extent — the step after alpha_key) or ``"color"``
    (distance from the corner-average background)."""

    def go():
        out = curation_auto_trim(src, dest, mode=mode, tolerance=tolerance)
        return {"dest": str(out)}

    return await _envelope._run_tool("auto_trim", go)


async def palette_quantize(
    src: str,
    dest: str,
    n_colors: int = 16,
    method: str = "median_cut",
) -> dict[str, Any]:
    """Reduce an image to a fixed palette (the limited-palette look). ``method``
    is ``"median_cut"``, ``"maximum_coverage"``, or ``"octree"``; ``n_colors``
    is 2-256. Transparency is preserved."""

    def go():
        out = curation_palette_quantize(src, dest, n_colors=n_colors, method=method)
        return {"dest": str(out)}

    return await _envelope._run_tool("palette_quantize", go)


async def sprite_sheet(
    srcs: list[str],
    dest: str,
    layout: str = "grid",
    padding: int = 0,
) -> dict[str, Any]:
    """Pack several sprites into one atlas plus a ``.frames.json`` map written
    next to it. ``layout`` is ``"grid"``, ``"row"``, or ``"column"``. Returns
    the atlas ``dest``."""

    def go():
        out = curation_sprite_sheet(srcs, dest, layout=layout, padding=padding)
        return {"dest": str(out)}

    return await _envelope._run_tool("sprite_sheet", go)


async def score_grid(src: str) -> dict[str, Any]:
    """Rank the four quadrants of a 2x2 grid on sharpness/contrast/edge-density
    so the agent picks the strongest candidate on evidence (then confirms with
    vision). Returns ``{ok, result: {scores}}`` sorted best-first."""

    def go():
        return {"scores": curation_score_grid(src)}

    return await _envelope._run_tool("score_grid", go)

"""Score the four quadrants of a Midjourney 2x2 grid for selection.

Selection today is the agent eyeballing the grid and passing a quadrant int.
``score_grid`` gives it a numeric ranking to pick on evidence (and to log a
reason), then confirm with vision. Advisory, not authoritative.

Pure-PIL — no numpy/cv2 — so it always runs (no optional extra) and stays cheap:

* sharpness    — stddev of a Laplacian-filtered grayscale (focus / detail).
* contrast     — stddev of the grayscale histogram.
* edge_density — fraction of strong-edge pixels after FIND_EDGES.

Each metric is min-max normalized across the four quadrants, then combined into
a weighted ``composite``; the result is sorted by ``composite`` descending.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageStat

from cascade_img.curation.crop_grid import QUADRANT_OFFSETS, crop_quadrant
from cascade_img.vocabulary import emit

# 3x3 discrete Laplacian; high response on edges/detail, ~0 on flat regions.
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, -1, 0, -1, 4, -1, 0, -1, 0], scale=1, offset=128)
_EDGE_THRESHOLD = 40  # 0-255: a FIND_EDGES pixel brighter than this is a "strong edge"
_DEFAULT_WEIGHTS = {"sharpness": 0.5, "contrast": 0.25, "edge_density": 0.25}


def _metrics(quad: Image.Image) -> dict[str, float]:
    gray = quad.convert("L")
    sharpness = ImageStat.Stat(gray.filter(_LAPLACIAN)).stddev[0]
    contrast = ImageStat.Stat(gray).stddev[0]
    edges = gray.filter(ImageFilter.FIND_EDGES)
    hist = edges.histogram()
    total = sum(hist) or 1
    strong = sum(hist[_EDGE_THRESHOLD:])
    edge_density = strong / total
    return {"sharpness": sharpness, "contrast": contrast, "edge_density": edge_density}


def _normalize(values: list[float]) -> list[float]:
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        return [0.0 for _ in values]  # all equal -> no signal
    return [(v - lo) / (hi - lo) for v in values]


def score_grid(
    src: str | Path | Image.Image,
    *,
    weights: dict[str, float] | None = None,
) -> list[dict]:
    """Rank a 2x2 grid's quadrants. Returns a list of
    ``{slot, sharpness, contrast, edge_density, composite}`` sorted by
    ``composite`` descending (best first)."""
    w = {**_DEFAULT_WEIGHTS, **(weights or {})}

    opened_here = False
    grid: Image.Image  # Image.open returns the ImageFile subclass; widen the var
    if isinstance(src, (str, Path)):
        grid = Image.open(src)
        opened_here = True
    else:
        grid = src
    try:
        raw = {slot: _metrics(crop_quadrant(grid, slot)) for slot in QUADRANT_OFFSETS}
    finally:
        if opened_here:
            grid.close()

    slots = sorted(raw)
    norm = {
        metric: dict(zip(slots, _normalize([raw[s][metric] for s in slots]), strict=True))
        for metric in ("sharpness", "contrast", "edge_density")
    }

    scored = []
    for slot in slots:
        composite = sum(w[m] * norm[m][slot] for m in ("sharpness", "contrast", "edge_density"))
        scored.append(
            {
                "slot": slot,
                "sharpness": round(raw[slot]["sharpness"], 4),
                "contrast": round(raw[slot]["contrast"], 4),
                "edge_density": round(raw[slot]["edge_density"], 4),
                "composite": round(composite, 4),
            }
        )
    scored.sort(key=lambda r: r["composite"], reverse=True)

    emit(
        "GRID_SCORED",
        src=str(src) if opened_here else "<image>",
        tiles=len(scored),
        top_slot=scored[0]["slot"],
    )
    return scored

"""Pack curated sprites into one atlas plus a JSON frame map.

Replaces a one-file-per-sprite tree with a single sheet a game engine loads
once and indexes by name. Cells are sized to the largest sprite; frames are
keyed by each source file's stem. The map is written next to the atlas as
``<dest>.frames.json``.
"""

from __future__ import annotations

import json
import math
from collections.abc import Sequence
from pathlib import Path

from PIL import Image

from cascade_img.vocabulary import emit


def sprite_sheet(
    srcs: Sequence[str | Path],
    dest: str | Path,
    *,
    layout: str = "grid",
    padding: int = 0,
) -> Path:
    """Pack ``srcs`` into one atlas at ``dest`` plus a ``.frames.json`` map.

    Args:
        srcs: Paths to the sprites to pack.
        dest: Output path for the atlas PNG.
        layout: ``"grid"`` (square-ish), ``"row"``, or ``"column"``.
        padding: Pixels added to each cell's width and height.

    Returns:
        The resolved ``dest`` path.
    """
    if layout not in ("grid", "row", "column"):
        raise ValueError(
            f"sprite_sheet: unknown layout {layout!r}; expected 'grid', 'row', or 'column'."
        )
    src_paths = [Path(s) for s in srcs]
    if not src_paths:
        raise ValueError("sprite_sheet: srcs is empty; provide at least one sprite path.")

    loaded: list[tuple[Path, Image.Image]] = []
    for s in src_paths:
        with Image.open(s) as im:
            loaded.append((s, im.convert("RGBA").copy()))

    cell_w = max(im.size[0] for _, im in loaded) + padding
    cell_h = max(im.size[1] for _, im in loaded) + padding
    n = len(loaded)
    if layout == "row":
        cols, rows = n, 1
    elif layout == "column":
        cols, rows = 1, n
    else:
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)

    sheet_w, sheet_h = cols * cell_w, rows * cell_h
    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    frames: dict[str, dict[str, int]] = {}
    for i, (s, im) in enumerate(loaded):
        cx, cy = (i % cols) * cell_w, (i // cols) * cell_h
        sheet.paste(im, (cx, cy))
        frames[s.stem] = {"x": cx, "y": cy, "w": im.size[0], "h": im.size[1]}

    dest_p = Path(dest)
    dest_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest_p)
    map_p = dest_p.with_suffix(dest_p.suffix + ".frames.json")
    map_p.write_text(
        json.dumps({"sheet": dest_p.name, "layout": layout, "frames": frames}, indent=2),
        encoding="utf-8",
    )

    emit(
        "SPRITE_SHEET_PACKED",
        dest=str(dest_p),
        count=n,
        layout=layout,
        w=sheet_w,
        h=sheet_h,
    )
    return dest_p

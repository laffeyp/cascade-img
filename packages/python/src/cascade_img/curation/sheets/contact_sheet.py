"""Render a Midjourney 2x2 grid into one annotated contact sheet.

A grid is four candidates. An agent choosing among them with vision reads one
labelled image far more reliably than four separate crops: the index badge
("1".."4", optionally a score) gives it a stable handle to name its pick.
``contact_sheet`` repaints the grid and draws that badge on each panel.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cascade_img.curation._shared import QUADRANT_OFFSETS
from cascade_img.vocabulary import emit


def contact_sheet(
    src: str | Path,
    dest: str | Path,
    *,
    labels: bool = True,
    scores: dict[int, float] | None = None,
) -> Path:
    """Composite a 2x2 grid into a labelled contact sheet written to ``dest``.

    Args:
        src: Path to the grid image.
        dest: Output path for the annotated sheet.
        labels: Draw the 1-4 index badge on each panel.
        scores: Optional ``{slot: score}`` printed next to each index.

    Returns:
        The resolved ``dest`` path.
    """
    src_p, dest_p = Path(src), Path(dest)
    with Image.open(src_p) as grid:
        sheet = grid.convert("RGBA").copy()

    w, h = sheet.size
    qw, qh = w // 2, h // 2
    if labels:
        draw = ImageDraw.Draw(sheet)
        font = ImageFont.load_default()
        pad = 4
        for slot, (fx, fy) in QUADRANT_OFFSETS.items():
            x, y = fx * qw, fy * qh
            text = str(slot)
            if scores and slot in scores:
                text = f"{slot}  {scores[slot]:.2f}"
            box = draw.textbbox((0, 0), text, font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
            draw.rectangle(
                (x + pad, y + pad, x + pad + tw + 2 * pad, y + pad + th + 2 * pad),
                fill=(0, 0, 0, 200),
            )
            draw.text((x + 2 * pad, y + 2 * pad), text, fill=(255, 255, 255, 255), font=font)

    dest_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest_p)
    emit(
        "CONTACT_SHEET_RENDERED",
        src=str(src_p),
        dest=str(dest_p),
        tiles=len(QUADRANT_OFFSETS),
        w=w,
        h=h,
    )
    return dest_p

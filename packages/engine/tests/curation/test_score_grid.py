"""Behavior contract for score_grid: ranking + the GRID_SCORED signal."""

from __future__ import annotations

from PIL import Image, ImageDraw

from cascade_img.curation import score_grid
from cascade_img.vocabulary import clear, snapshot


def _grid_with_one_busy_quadrant(tmp_path):
    """64x64 grid; U1 (top-left 32x32) is a high-contrast checker, the other
    three quadrants flat gray. U1 should win on every metric."""
    g = Image.new("RGB", (64, 64), (128, 128, 128))
    d = ImageDraw.Draw(g)
    for x in range(0, 32, 4):
        for y in range(0, 32, 4):
            fill = (0, 0, 0) if (x + y) % 8 == 0 else (255, 255, 255)
            d.rectangle((x, y, x + 3, y + 3), fill=fill)
    p = tmp_path / "grid.png"
    g.save(p)
    return p


def test_ranks_busy_quadrant_first_and_emits_signal(tmp_path):
    clear()
    scores = score_grid(_grid_with_one_busy_quadrant(tmp_path))
    assert len(scores) == 4
    assert {s["slot"] for s in scores} == {1, 2, 3, 4}
    assert scores[0]["slot"] == 1  # the busy checker quadrant wins
    comps = [s["composite"] for s in scores]
    assert comps == sorted(comps, reverse=True)  # sorted best-first
    rec = snapshot()[-1]
    assert rec["tag"] == "GRID_SCORED"
    assert rec["payload"]["top_slot"] == 1
    assert rec["payload"]["tiles"] == 4


def test_uniform_grid_normalizes_to_zero_without_dividing(tmp_path):
    """A flat grid has no signal: every metric is equal across quadrants, so
    composites normalize to 0.0 and nothing divides by zero."""
    src = tmp_path / "flat.png"
    Image.new("RGB", (40, 40), (100, 100, 100)).save(src)
    scores = score_grid(src)
    assert len(scores) == 4
    assert all(s["composite"] == 0.0 for s in scores)

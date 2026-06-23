"""Measure how cleanly a looping video closes.

A looping video's quality is seam cleanliness: does the last frame match the
first? Rather than make a human eyeball the seam, report it as a number — the
normalized (0-1) pixel distance between the last and first frames (low = clean
loop). The video analog of the classic "click at the loop point" audio check.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageChops, ImageStat

from cascade_img.vocabulary import emit


def loop_seam_delta(src: str | Path) -> dict:
    """Return ``{src, frame_count, loop_seam_delta}`` for the video at ``src``.

    ``loop_seam_delta`` is the mean absolute per-channel difference between the
    last and first frames, normalized to 0-1: ~0 is a seamless loop, higher
    means a visible jump at the wrap. Emits ``LOOP_SEAM_MEASURED``. A single-frame
    image trivially reports 0.0.
    """
    src_p = Path(src)
    with Image.open(src_p) as im:
        n = int(getattr(im, "n_frames", 1))
        im.seek(0)
        first = im.convert("RGB").copy()
        im.seek(n - 1)
        last = im.convert("RGB").copy()

    diff = ImageChops.difference(first, last)
    delta = round(sum(ImageStat.Stat(diff).mean) / (3 * 255), 4)
    emit("LOOP_SEAM_MEASURED", src=str(src_p), frame_count=n, delta=delta)
    return {"src": str(src_p), "frame_count": n, "loop_seam_delta": delta}

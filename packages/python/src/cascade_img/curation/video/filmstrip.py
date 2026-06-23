"""Project a video into a vision-readable filmstrip + signature.

An agent cannot "inspect with vision" an animated webp the way it reads a still
PNG — the curation step has no spatial frame to look at. So sample N
keyframes (first / evenly-spaced / last) into one labeled contact sheet the
agent reads with vision, AND emit a structured signature (frame_count,
duration_s, fps, dims). The video then speaks for itself. This is the video
analog of an audio waveform-with-time-markers and the grid ``contact_sheet``.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from cascade_img.vocabulary import emit


def _signature(im: Image.Image) -> tuple[int, float, float]:
    """Return ``(frame_count, duration_s, fps)`` for an opened animated image.

    Sums per-frame durations (animated webp/gif carry ``info['duration']`` in ms
    after ``seek``); a still image is one frame with zero duration."""
    n = int(getattr(im, "n_frames", 1))
    total_ms = 0
    for k in range(n):
        im.seek(k)
        total_ms += int(im.info.get("duration", 0) or 0)
    im.seek(0)
    duration_s = round(total_ms / 1000, 3)
    fps = round(n / duration_s, 2) if duration_s else float(n)
    return n, duration_s, fps


def _sample_indices(n: int, frames: int) -> list[int]:
    """Evenly-spaced frame indices including the first and last frame."""
    if n <= 1:
        return [0]
    count = max(1, min(frames, n))
    if count == 1:
        return [0]
    return sorted({round(i * (n - 1) / (count - 1)) for i in range(count)})


def video_filmstrip(src: str | Path, dest: str | Path, *, frames: int = 5) -> dict:
    """Render ``frames`` evenly-spaced keyframes of the video at ``src`` into one
    labeled horizontal filmstrip at ``dest`` (PNG), and emit the video signature.

    Returns ``{dest, frame_count, duration_s, fps, w, h}`` — the same signature
    carried on ``VIDEO_FILMSTRIP_RENDERED``. Works on any animated webp (native
    ``--video`` output or an ``animate_*`` result).
    """
    src_p, dest_p = Path(src), Path(dest)
    with Image.open(src_p) as im:
        n, duration_s, fps = _signature(im)
        w, h = im.size
        thumbs: list[tuple[int, Image.Image]] = []
        for idx in _sample_indices(n, frames):
            im.seek(idx)
            thumbs.append((idx, im.convert("RGB").copy()))

    pad, label_h = 4, 14
    strip_w = len(thumbs) * w + (len(thumbs) + 1) * pad
    strip_h = h + label_h + 2 * pad
    sheet = Image.new("RGB", (strip_w, strip_h), (20, 20, 20))
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default()
    x = pad
    for idx, thumb in thumbs:
        sheet.paste(thumb, (x, label_h + pad))
        draw.text((x + 1, 2), f"f{idx}", fill=(255, 255, 255), font=font)
        x += w + pad

    dest_p.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(dest_p)
    emit(
        "VIDEO_FILMSTRIP_RENDERED",
        src=str(src_p),
        dest=str(dest_p),
        frame_count=n,
        duration_s=duration_s,
        fps=fps,
        w=w,
        h=h,
    )
    return {
        "dest": str(dest_p),
        "frame_count": n,
        "duration_s": duration_s,
        "fps": fps,
        "w": w,
        "h": h,
    }

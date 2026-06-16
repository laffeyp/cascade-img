"""Video curation primitives: video_filmstrip (F32) + loop_seam_delta (F33).

These make a temporal artifact inspectable — a filmstrip still the agent reads
with vision plus a numeric signature, and a loop-seam quality number. Hermetic:
they operate on an animated webp built in-process with PIL.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

from cascade_img.curation.video import loop_seam_delta, video_filmstrip
from cascade_img.vocabulary import clear, snapshot


def _make_webp(path: Path, *, frames: int = 6, size=(32, 32), clean_loop: bool = True) -> None:
    """Write a lossless animated webp whose frames step in color. ``clean_loop``
    makes the last frame identical to the first (seamless)."""
    imgs = [Image.new("RGB", size, ((i * 40) % 256, 0, 0)) for i in range(frames)]
    if clean_loop:
        imgs[-1] = imgs[0].copy()
    imgs[0].save(
        path,
        save_all=True,
        append_images=imgs[1:],
        duration=100,
        loop=0,
        lossless=True,
        format="WEBP",
    )


def _tags():
    return [r["tag"] for r in snapshot()]


def test_filmstrip_samples_frames_and_emits_signature(tmp_path):
    clear()
    src = tmp_path / "v.webp"
    _make_webp(src, frames=6)
    dest = tmp_path / "strip.png"

    sig = video_filmstrip(str(src), str(dest), frames=3)

    assert dest.exists()
    assert sig["frame_count"] == 6
    # duration_s is best-effort: PIL doesn't expose per-frame duration for webp,
    # so it's a float that may be 0; frame_count + dims are the reliable signature.
    assert isinstance(sig["duration_s"], int | float)
    assert sig["w"] == 32 and sig["h"] == 32
    # the filmstrip still is wider than one frame (multiple keyframes laid out)
    with Image.open(dest) as strip:
        assert strip.size[0] > 32
    assert "VIDEO_FILMSTRIP_RENDERED" in _tags()


def test_filmstrip_handles_more_frames_than_exist(tmp_path):
    """Asking for more keyframes than the video has must not crash."""
    clear()
    src = tmp_path / "short.webp"
    # distinct frames (clean_loop would make 2 identical frames the webp encoder
    # collapses to one); we only need >1 frame and frames>n requested.
    _make_webp(src, frames=2, clean_loop=False)
    sig = video_filmstrip(str(src), str(tmp_path / "s.png"), frames=10)
    assert sig["frame_count"] == 2


def test_loop_seam_delta_zero_for_clean_loop(tmp_path):
    clear()
    src = tmp_path / "loop.webp"
    _make_webp(src, frames=6, clean_loop=True)  # last == first
    r = loop_seam_delta(str(src))
    assert r["frame_count"] == 6
    assert r["loop_seam_delta"] == 0.0  # seamless
    assert "LOOP_SEAM_MEASURED" in _tags()


def test_loop_seam_delta_high_for_jump(tmp_path):
    clear()
    src = tmp_path / "jump.webp"
    _make_webp(src, frames=6, clean_loop=False)  # last (200,0,0) != first (0,0,0)
    r = loop_seam_delta(str(src))
    assert r["loop_seam_delta"] > 0.1  # a clear seam

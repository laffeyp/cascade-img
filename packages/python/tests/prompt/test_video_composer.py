"""Behavior contract for PromptComposer.compose_video — native image→video prompts.

V-1 scope: composition only. A video prompt is ``<image_url> [text] --video`` plus
the video-specific params (--motion/--raw/--loop/--end/--bs); image params are a
disjoint surface (MJ strips them under --video) so they are not accepted here.
Conflicts (bad motion/bs, loop+end together, flag injection, empty url) fail at
composition, per the validate-at-construction contract.
"""

from __future__ import annotations

import pytest

from cascade_img.prompt.composer import PromptComposer


def _c() -> PromptComposer:
    return PromptComposer()


def test_minimal_video_prompt_leads_with_url_then_video_flag():
    p = _c().compose_video("https://cdn/start.png")
    assert p == "https://cdn/start.png --video"


def test_text_sits_between_url_and_video_flag():
    p = _c().compose_video("https://cdn/start.png", text="slow zoom in")
    assert p == "https://cdn/start.png slow zoom in --video"


def test_motion_emits_flag_and_validates():
    assert "--motion low" in _c().compose_video("https://cdn/s.png", motion="low")
    assert "--motion high" in _c().compose_video("https://cdn/s.png", motion="high")
    with pytest.raises(ValueError, match="motion must be one of"):
        _c().compose_video("https://cdn/s.png", motion="medium")


def test_raw_and_loop_flags():
    p = _c().compose_video("https://cdn/s.png", raw=True, loop=True)
    assert "--raw" in p
    assert "--loop" in p


def test_loop_produces_a_looping_video_flag():
    """The headline video feature: --loop reuses the start frame as the end frame."""
    p = _c().compose_video("https://cdn/s.png", loop=True)
    assert p == "https://cdn/s.png --video --loop"


def test_end_frame_emits_end_url():
    p = _c().compose_video("https://cdn/s.png", end_frame="https://cdn/end.png")
    assert "--end https://cdn/end.png" in p


def test_loop_and_end_frame_are_mutually_exclusive():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _c().compose_video("https://cdn/s.png", loop=True, end_frame="https://cdn/end.png")


def test_batch_size_emits_bs_and_validates():
    assert "--bs 4" in _c().compose_video("https://cdn/s.png", batch_size=4)
    for bad in (0, 3, 5):
        with pytest.raises(ValueError, match="batch_size must be one of"):
            _c().compose_video("https://cdn/s.png", batch_size=bad)


def test_empty_image_url_rejected():
    for bad in ("", "   ", "\t"):
        with pytest.raises(ValueError, match="requires a starting-frame image_url"):
            _c().compose_video(bad)


def test_flag_injection_rejected_in_video_fields():
    with pytest.raises(ValueError, match="--"):
        _c().compose_video("https://cdn/s.png --loop")  # flag smuggled into url
    with pytest.raises(ValueError, match="--"):
        _c().compose_video("https://cdn/s.png", text="zoom --bs 4")
    with pytest.raises(ValueError, match="--"):
        _c().compose_video("https://cdn/s.png", end_frame="https://cdn/e.png --loop")


def test_full_surface_order_and_content():
    p = _c().compose_video(
        "https://cdn/start.png",
        text="gentle drift",
        motion="high",
        raw=True,
        end_frame="https://cdn/end.png",
        batch_size=2,
    )
    # url leads, text next, then --video, then the video params.
    assert p == (
        "https://cdn/start.png gentle drift --video --motion high --raw "
        "--end https://cdn/end.png --bs 2"
    )


def test_no_image_params_leak_into_a_video_prompt():
    """A video prompt carries only video-specific flags — none of the image
    surface (--ar/--sref/--oref/--q/--hd/--chaos/--v) appears."""
    p = _c().compose_video("https://cdn/s.png", motion="low", loop=True, batch_size=4)
    for forbidden in ("--ar", "--sref", "--oref", "--q", "--hd", "--chaos", "--v ", "--s "):
        assert forbidden not in p

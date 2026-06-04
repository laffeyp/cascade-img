"""Live, gating e2e coverage of every non-aesthetic capability.

Each test drives the real bridge → Midjourney and asserts a *measurable* outcome
via the image-property checks (animate produced an animation, alpha-key produced
transparency, an action produced a valid distinct artifact, the param surface is
accepted). What's deliberately NOT here: aesthetic judgments ("is this good / the
right subject") — those need a human or a CLIP-class model, not a property check.

Gated by CASCADE_LIVE=1 + CASCADE_ENV_FILE (the fixtures skip otherwise). All
tests share one bridge and one base ``upscale="all"`` render (see conftest) to
keep the live render count — and the credit cost — minimal.
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e


def _wait_for_derived(backend, job_id: str, action_kind: str, *, timeout: int = 240) -> dict:
    """Poll ``status`` until a derived result of ``action_kind`` with a saved path
    appears; return that entry."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        for d in backend.status(job_id).get("derived", []):
            if d.get("action_kind") == action_kind and d.get("path"):
                return d
        time.sleep(3)
    raise AssertionError(f"no derived '{action_kind}' on {job_id} within {timeout}s")


# --------------------------- generation ---------------------------


def test_grid_and_four_upscales_are_valid_images(base_job, checks):
    assert checks.is_valid_image(base_job["grid_path"]), "grid is not a valid image"
    paths = base_job["upscale_paths"]
    assert len(paths) == 4, f"upscale='all' should yield 4 images, got {paths}"
    for slot, p in paths.items():
        assert checks.is_valid_image(p), f"upscale slot {slot} invalid: {p}"


# --------------------------- response-message actions ---------------------------


def test_action_animate_produces_an_animation(live_backend, base_job, checks):
    live_backend.action(base_job["job_id"], "animate_low")
    d = _wait_for_derived(live_backend, base_job["job_id"], "animation", timeout=300)
    assert checks.is_animated(d["path"]), f"animate_low did not yield a multi-frame file: {d}"
    assert checks.frame_count(d["path"]) > 1


def test_action_vary_produces_a_distinct_image(live_backend, base_job, checks):
    live_backend.action(base_job["job_id"], "vary_subtle")
    d = _wait_for_derived(live_backend, base_job["job_id"], "variation")
    assert checks.is_valid_image(d["path"])
    # A variation is a fresh render, so it must differ from the source upscale.
    source = next(iter(base_job["upscale_paths"].values()))
    assert checks.images_differ(d["path"], source), "variation looks identical to the source"


def test_action_zoom_out_produces_a_valid_image(live_backend, base_job, checks):
    live_backend.action(base_job["job_id"], "zoom_out_2x")
    d = _wait_for_derived(live_backend, base_job["job_id"], "zoom")
    assert checks.is_valid_image(d["path"])


def test_action_pan_produces_a_valid_image(live_backend, base_job, checks):
    live_backend.action(base_job["job_id"], "pan_right")
    d = _wait_for_derived(live_backend, base_job["job_id"], "pan")
    assert checks.is_valid_image(d["path"])


def test_action_upscale_variant_produces_a_valid_image(live_backend, base_job, checks):
    live_backend.action(base_job["job_id"], "upscale_subtle")
    d = _wait_for_derived(live_backend, base_job["job_id"], "upscale")
    assert checks.is_valid_image(d["path"])


def test_action_favorite_succeeds_with_no_artifact(live_backend, base_job):
    """favorite bookmarks the image in Midjourney — it must succeed but produce
    no downloaded artifact (nothing lands in derived for it)."""
    before = {
        d.get("message_id") for d in live_backend.status(base_job["job_id"]).get("derived", [])
    }
    live_backend.action(base_job["job_id"], "favorite")
    time.sleep(20)
    after = live_backend.status(base_job["job_id"]).get("derived", [])
    favorites = [
        d for d in after if d.get("message_id") not in before and d.get("action_kind") == "favorite"
    ]
    assert favorites == [], f"favorite should produce no artifact, got {favorites}"


# --------------------------- curation on real output ---------------------------


def test_curation_pipeline_on_live_grid(base_job, checks, tmp_path: Path):
    """crop a quadrant from the real grid, alpha-key its white background, and
    promote — asserting the cut-out is a valid image with real transparency."""
    from cascade_img.curation import alpha_key_corners, crop_quadrant, promote

    quad = crop_quadrant(base_job["grid_path"], 1)
    cropped = tmp_path / "cropped.png"
    quad.save(cropped)
    assert checks.is_valid_image(cropped)

    keyed_img = alpha_key_corners(quad, tolerance=40, method="flood")
    keyed = tmp_path / "keyed.png"
    keyed_img.save(keyed)
    assert checks.has_transparency(keyed), "alpha-key did not cut the white background"

    out = tmp_path / "promoted.png"
    promote(str(keyed), str(out))
    assert out.exists() and checks.is_valid_image(out)


# --------------------------- prompt-parameter surface ---------------------------


def test_render_control_params_are_accepted(live_backend, checks):
    """Prove Midjourney accepts cascade-img's render-control param surface
    end-to-end: a single grid render carrying exp / chaos / weird / stop /
    quality / seed / stylize must come back ``done`` with a valid image. (We
    can't assert a param *changed* the image — two renders differ from MJ's own
    randomness regardless — only that the whole surface is accepted and renders.)
    """
    from cascade_img.prompt.composer import ParamStack, PromptComposer, StyleStack, Subject

    prompt = PromptComposer().compose(
        Subject(text="a simple flat icon of a blue square, centered, plain white background"),
        style=StyleStack(stylize=200),
        params=ParamStack(exp=15, chaos=15, weird=50, stop=90, quality=2, seed=4242),
        aspect_ratio="1:1",
    )
    res = live_backend.imagine(prompt, asset_id="captest_params", upscale=None)
    rec = live_backend.wait(res["job_id"], timeout=300)
    assert rec.get("status") == "done", f"param render did not finish: {rec}"
    assert checks.is_valid_image(rec["image_path"] or rec["grid_path"])

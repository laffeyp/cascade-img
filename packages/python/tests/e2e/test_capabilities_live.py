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

import json
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


# --- observation helpers: verify against the durable signal trace ---
# The spawned bridge appends every vocabulary signal to CASCADE_EVENT_LOG (the
# event_log_path fixture). Reading it back is how this suite grades behavior — the
# typed event stream is the source of truth, not a status() poll (same idiom as
# test_trace_gate_live._read_events).


def _job_signals(event_log_path: Path, job_id: str) -> list[dict]:
    if not event_log_path.exists():
        return []
    out = []
    for line in event_log_path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        e = json.loads(line)
        if (e.get("payload") or {}).get("job_id") == job_id:
            out.append(e)
    return out


def _find_signal(event_log_path: Path, job_id: str, tag: str, **payload_match) -> dict | None:
    for e in _job_signals(event_log_path, job_id):
        if e.get("tag") != tag:
            continue
        p = e.get("payload") or {}
        if all(p.get(k) == v for k, v in payload_match.items()):
            return e
    return None


def _trace_tail(event_log_path: Path, job_id: str, n: int = 14) -> str:
    """A compact, readable tail of the job's signal trace for failure messages —
    so a live failure reports what the program SAID happened, not a bare timeout."""
    evs = _job_signals(event_log_path, job_id)
    if not evs:
        return f"(no signals for {job_id} in the trace)"
    parts = []
    for e in evs[-n:]:
        p = e.get("payload") or {}
        qual = p.get("action") or p.get("action_kind") or p.get("surface_kind") or ""
        parts.append(f"{e['tag']}({qual})" if qual else e["tag"])
    return " -> ".join(parts)


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


def test_action_upscale_variant_is_v7_only(live_backend, base_job):
    """Re-upscale (Subtle/Creative) is a **V7-only** action. V8.1 renders native
    HD and drops the 2x re-upscalers — verified live 2026-06-14: pressing
    ``upscale_subtle`` on a V8.1 image (the default ``base_job``) returns a clean
    "no 'upscale_subtle' button found" error. We assert that V8.1 behavior
    explicitly, so the boundary is graded, not assumed."""
    from cascade_img.backends.midjourney_discord.bridge_client import BridgeError

    # Branch on the stable code, never the message (the project's error contract).
    with pytest.raises(BridgeError) as exc:
        live_backend.action(base_job["job_id"], "upscale_subtle")
    assert exc.value.code == "BUTTON_NOT_FOUND", (
        f"expected the V8.1 re-upscaler absence to surface as the stable "
        f"BUTTON_NOT_FOUND code; got {exc.value.code!r}"
    )


def test_action_upscale_variant_produces_a_valid_image_on_v7(live_backend, base_job_v7, checks):
    """On a V7 render the Subtle re-upscaler exists and produces a valid image."""
    live_backend.action(base_job_v7["job_id"], "upscale_subtle")
    d = _wait_for_derived(live_backend, base_job_v7["job_id"], "upscale")
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
    end-to-end, on BOTH model versions, since the surface is version-gated:

    - V8.1 (default): exp / chaos / weird / seed / stylize / tile + ``--hd``
      (native 2K). V8.1 dropped ``--q``, so quality is not in this arm.
    - V8.1 ``--sd`` (native 1024px): a separate render, since ``--hd`` and
      ``--sd`` are mutually exclusive — without its own arm the new ``--sd``
      flag would never reach a live render (only string-asserted), exactly the
      hole the ``--stop`` regression taught us to close (review #5).
    - V7: the same shared surface + ``--q`` (V7-only) via ``version='7'``.

    Each render must come back ``done`` with a valid image. (We can't assert a
    param *changed* the image — two renders differ from MJ's own randomness
    regardless — only that the whole surface is accepted and renders. This is
    the test that caught ``--stop`` being v6-only and now guards the v7→v8.1
    grammar split.)
    """
    from cascade_img.prompt.composer import ParamStack, PromptComposer, StyleStack, Subject

    composer = PromptComposer()
    subject = Subject(text="a simple flat icon of a blue square, centered, plain white background")

    # V8.1 surface (default version): shared render controls + native-HD --hd.
    v8_prompt = composer.compose(
        subject,
        style=StyleStack(stylize=200),
        params=ParamStack(exp=15, chaos=15, weird=50, seed=4242, tile=True, hd=True),
        aspect_ratio="1:1",
    )
    v8 = live_backend.imagine(v8_prompt, asset_id="captest_params_v8", upscale=None)
    v8_rec = live_backend.wait(v8["job_id"], timeout=300)
    assert v8_rec.get("status") == "done", f"V8.1 param render did not finish: {v8_rec}"
    assert checks.is_valid_image(v8_rec["image_path"] or v8_rec["grid_path"])

    # V8.1 --sd (native 1024px): its own render — mutually exclusive with --hd, so
    # it needs a standalone arm to get sent to a real MJ render at all.
    sd_prompt = composer.compose(
        subject,
        params=ParamStack(sd=True),
        aspect_ratio="1:1",
    )
    assert "--sd" in sd_prompt
    sd = live_backend.imagine(sd_prompt, asset_id="captest_params_sd", upscale=None)
    sd_rec = live_backend.wait(sd["job_id"], timeout=300)
    assert sd_rec.get("status") == "done", f"V8.1 --sd render did not finish: {sd_rec}"
    assert checks.is_valid_image(sd_rec["image_path"] or sd_rec["grid_path"])

    # V7 surface: the shared controls plus --q (V7-only), via version='7'.
    v7_prompt = composer.compose(
        subject,
        style=StyleStack(stylize=200),
        params=ParamStack(exp=15, chaos=15, weird=50, quality=2, seed=4242, tile=True),
        aspect_ratio="1:1",
        version="7",
    )
    v7 = live_backend.imagine(v7_prompt, asset_id="captest_params_v7", upscale=None)
    v7_rec = live_backend.wait(v7["job_id"], timeout=300)
    assert v7_rec.get("status") == "done", f"V7 param render did not finish: {v7_rec}"
    assert checks.is_valid_image(v7_rec["image_path"] or v7_rec["grid_path"])


# --------------------------- native video (--video --loop) ---------------------------


def test_native_video_loop_renders(live_backend, checks):
    """Native ``--video --loop`` end-to-end through the bridge's /video path:
    generate a starting image, fire a LOOPING video from its URL, and assert a
    valid animated webp lands. Verifies F34 bind-on-vendor-echo routing live —
    video prompts carry no --no token, so the bridge must bind MJ's echoed
    s.mj.run short URL to route the result home."""
    from cascade_img.prompt.composer import PromptComposer, Subject

    composer = PromptComposer()
    # 1) a starting frame — a single upscale yields a SOLO image URL MJ can fetch.
    seed = live_backend.imagine(
        composer.compose(Subject(text="a solid red circle on a plain white background, flat icon")),
        asset_id="captest_vidseed",
        upscale="1",
    )
    seed_rec = live_backend.wait(seed["job_id"], timeout=300)
    assert seed_rec.get("status") == "done", f"video seed render did not finish: {seed_rec}"
    start_url = seed_rec.get("image_url")
    assert start_url, f"no SOLO image_url on the seed job to animate: {seed_rec}"

    # 2) native looping video from that URL, fired through /video.
    prompt = composer.compose_video(start_url, loop=True, motion="low")
    vid = live_backend.generate_video(prompt, asset_id="captest_vidloop")
    vid_rec = live_backend.wait(vid["job_id"], timeout=420)
    assert vid_rec.get("status") == "done", f"native video did not finish: {vid_rec}"
    out = vid_rec.get("image_path") or vid_rec.get("grid_path")
    assert out and checks.is_valid_image(out), f"video result is not a valid file: {out}"
    assert checks.is_animated(out), f"video result is not animated (multi-frame): {out}"

    # F32/F33 applied to the real video: a filmstrip the agent could read with
    # vision, and a loop-seam quality number — live-verifying the invented
    # techniques against a genuine MJ animated webp.
    from cascade_img.curation.video import loop_seam_delta, video_filmstrip

    strip = str(Path(out).with_suffix(".filmstrip.png"))
    sig = video_filmstrip(out, strip, frames=4)
    assert sig["frame_count"] > 1, f"real video should be multi-frame: {sig}"
    assert Path(strip).exists()
    seam = loop_seam_delta(out)
    assert 0.0 <= seam["loop_seam_delta"] <= 1.0, f"seam out of range: {seam}"


def test_native_video_upscale_action_routes_to_derived(live_backend, event_log_path):
    """V-3: the native-video result-action chain, graded against the durable signal
    trace (the codebase's observation check style — read the typed event stream,
    don't poll status blind). Each rung is both a routed ``derived`` artifact AND a
    signal in the trace:

        generate_video        -> VIDEO_RECEIVED, JOB_COMPLETED
        mj_action video_upscale -> MJ_ACTION_REQUESTED(video_upscale)
                                   -> MJ_DERIVED_RECEIVED + MJ_ACTION_SURFACE_REGISTERED(video_solo)
        mj_action extend_high   -> MJ_ACTION_REQUESTED(extend_high) -> MJ_DERIVED_RECEIVED

    The extend step is driven by the slot the trace says was registered, and a
    failure reports the job's signal tail (what the program SAID happened) rather
    than a bare timeout."""
    from cascade_img.prompt.composer import PromptComposer, Subject

    composer = PromptComposer()
    seed = live_backend.imagine(
        composer.compose(
            Subject(text="a solid green circle on a plain white background, flat icon")
        ),
        asset_id="captest_vidact_seed",
        upscale="1",
    )
    seed_rec = live_backend.wait(seed["job_id"], timeout=300)
    assert seed_rec.get("status") == "done", f"seed did not finish: {seed_rec}"
    start = seed_rec.get("image_url")
    assert start, f"no SOLO image_url: {seed_rec}"

    vid = live_backend.generate_video(
        composer.compose_video(start, loop=True), asset_id="captest_vidact"
    )
    job_id = vid["job_id"]
    vid_rec = live_backend.wait(job_id, timeout=420)
    assert vid_rec.get("status") == "done", f"video did not finish: {vid_rec}"
    # observation check: native-video generation is in the trace as VIDEO_RECEIVED
    assert _find_signal(event_log_path, job_id, "VIDEO_RECEIVED"), (
        f"no VIDEO_RECEIVED in trace; tail: {_trace_tail(event_log_path, job_id)}"
    )

    # press video_virtual_upscale on slot 1 → a SOLO mp4 that must route to derived
    live_backend.action(job_id, "video_upscale", slot=1)
    d = _wait_for_derived(live_backend, job_id, "animation", timeout=300)
    assert Path(d["path"]).exists(), f"derived SOLO not on disk: {d}"
    assert Path(d["path"]).suffix.lower() in (".mp4", ".webp", ".mov"), f"unexpected derived: {d}"
    # the press and the surface registration are typed events, not silent state
    assert _find_signal(event_log_path, job_id, "MJ_ACTION_REQUESTED", action="video_upscale"), (
        f"video_upscale press not in trace; tail: {_trace_tail(event_log_path, job_id)}"
    )
    surface = _find_signal(
        event_log_path, job_id, "MJ_ACTION_SURFACE_REGISTERED", surface_kind="video_solo"
    )
    assert surface is not None, (
        f"the SOLO landed but registered no extendable surface signal; "
        f"tail: {_trace_tail(event_log_path, job_id)}"
    )

    # V-3 extend chain: drive extend off the slot the TRACE says was registered
    # (grid-aligned per the live probe), then require the extended clip to route
    # back to derived AND the press to appear in the trace.
    ext_slot = surface["payload"]["slot"]
    n_before = len(live_backend.status(job_id).get("derived", []))
    live_backend.action(job_id, "extend_high", slot=ext_slot)
    deadline = time.time() + 360
    extended = None
    while time.time() < deadline:
        derived = [
            x
            for x in live_backend.status(job_id).get("derived", [])
            if x.get("action_kind") == "animation" and x.get("path")
        ]
        if len(derived) > n_before:
            extended = derived[-1]
            break
        time.sleep(3)
    # structured diagnosis: distinguish "press never fired" from "MJ produced nothing"
    assert _find_signal(event_log_path, job_id, "MJ_ACTION_REQUESTED", action="extend_high"), (
        f"extend_high never emitted MJ_ACTION_REQUESTED (press failed); "
        f"tail: {_trace_tail(event_log_path, job_id)}"
    )
    assert extended is not None, (
        f"extend_high pressed but no extended clip routed within 360s. "
        f"Signal trace for {job_id}: {_trace_tail(event_log_path, job_id)}"
    )
    assert Path(extended["path"]).exists(), f"extended clip not on disk: {extended}"

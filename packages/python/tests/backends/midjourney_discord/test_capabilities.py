"""Drift guard: MIDJOURNEY_DISCORD_CAPABILITIES.prompt_parts must stay complete
versus what PromptComposer can actually emit. This is the check that would have
caught the capabilities list omitting the entire ParamStack."""

from __future__ import annotations

from cascade_img.backends.midjourney_discord.bridge_client import (
    MIDJOURNEY_DISCORD_CAPABILITIES,
)
from cascade_img.prompt.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.vocabulary import clear, snapshot


def test_capabilities_cover_composer():
    """Compose every part the composer can emit and assert each emitted token is
    declared in the backend's capabilities. Because feature support is
    version-gated (oref/ow/quality are V7-only; hd/sd are V8-family-only), the full
    surface can't be emitted in one call — so we compose a V7 prompt (with
    oref+quality) and a V8.1 prompt (with hd+sd) and union their emitted parts.
    ``style_raw`` is a real capability but isn't recorded as a used-part token,
    so it's added explicitly."""
    common = {
        "subject": Subject(
            text="a subject",
            constraints=["a constraint"],
            negatives=["text"],
            image_prompts=["https://cdn/ref.png"],
            image_weight=2.0,
        ),
        "style": StyleStack(
            moodboard="m1", sref="https://cdn/s.png", sw=200, stylize=50, style_raw=True
        ),
        "aspect_ratio": "16:9",
    }
    emitted: set[str] = set()

    # V7 path: exercises the V7-only features (oref/ow + quality).
    clear()
    PromptComposer().compose(
        **common,
        identity=IdentityStack(oref="https://cdn/o.png", ow=400),
        params=ParamStack(tile=True, exp=25, chaos=10, weird=20, quality=2, seed=7),
        version="7",
    )
    emitted |= set(snapshot()[-1]["payload"]["prompt_parts_used"])

    # V8.1 path: exercises the V8-family-only features (hd; sd is hd's mutually
    # exclusive sibling, covered separately below).
    clear()
    PromptComposer().compose(
        **common,
        params=ParamStack(tile=True, exp=25, chaos=10, weird=20, hd=True, seed=7),
        version="8.1",
    )
    emitted |= set(snapshot()[-1]["payload"]["prompt_parts_used"])

    # sd is mutually exclusive with hd, so emit it in its own compose.
    clear()
    PromptComposer().compose(common["subject"], params=ParamStack(sd=True), version="8.1")
    emitted |= set(snapshot()[-1]["payload"]["prompt_parts_used"])

    declared = set(MIDJOURNEY_DISCORD_CAPABILITIES.prompt_parts)
    assert emitted | {"style_raw"} == declared, (
        f"capabilities drift — composer emits {sorted(emitted)}, "
        f"capabilities declares {sorted(declared)}"
    )


def test_capabilities_declare_versions():
    """The backend declares the selectable model versions and the default."""
    caps = MIDJOURNEY_DISCORD_CAPABILITIES
    assert caps.default_version == "8.1"
    assert set(caps.versions) == {"7", "8", "8.1"}


def test_capability_default_version_matches_composer_default():
    """Drift guard (review F4): the declared default_version must equal the
    composer's single-source default, so bumping one without the other fails
    here instead of shipping an inconsistent capability surface. Also confirms
    the declared default is actually a version the composer accepts."""
    from cascade_img.prompt.composer import _DEFAULT_VERSION, _SUPPORTED_VERSIONS

    caps = MIDJOURNEY_DISCORD_CAPABILITIES
    assert caps.default_version == _DEFAULT_VERSION
    assert _DEFAULT_VERSION in _SUPPORTED_VERSIONS
    assert set(caps.versions) == set(_SUPPORTED_VERSIONS)

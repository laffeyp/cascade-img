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
    """Compose with every part set, then assert every emitted prompt-part token is
    declared in the backend's capabilities. ``style_raw`` is a real capability but
    isn't recorded as a used-part token, so it's added explicitly."""
    clear()
    PromptComposer().compose(
        Subject(
            text="a subject",
            constraints=["a constraint"],
            negatives=["text"],
            image_prompts=["https://cdn/ref.png"],
            image_weight=2.0,
        ),
        style=StyleStack(
            moodboard="m1", sref="https://cdn/s.png", sw=200, stylize=50, style_raw=True
        ),
        identity=IdentityStack(oref="https://cdn/o.png", ow=400),
        params=ParamStack(tile=True, exp=25, chaos=10, weird=20, quality=2, seed=7),
        aspect_ratio="16:9",
    )
    emitted = set(snapshot()[-1]["payload"]["prompt_parts_used"])
    declared = set(MIDJOURNEY_DISCORD_CAPABILITIES.prompt_parts)
    assert emitted | {"style_raw"} == declared, (
        f"capabilities drift — composer emits {sorted(emitted)}, "
        f"capabilities declares {sorted(declared)}"
    )

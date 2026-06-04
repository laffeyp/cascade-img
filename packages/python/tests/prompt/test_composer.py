"""Behavior contract for PromptComposer.

Validates the v7 prompt-string assembly across the four facet combinations
the consumer can build, plus the signal payload on each.
"""

from __future__ import annotations

import pytest

from cascade_img.prompt.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.vocabulary import clear, snapshot


def test_subject_only_emits_minimal_prompt():
    clear()
    p = PromptComposer().compose(Subject(text="a mountain"))
    # No moodboard, no sref, no oref. style_raw default-on.
    assert p == "a mountain --ar 1:1 --v 7 --style raw"
    rec = snapshot()[-1]
    assert rec["tag"] == "PROMPT_COMPOSED"
    assert rec["payload"]["prompt_parts_used"] == []
    assert rec["payload"]["aspect_ratio"] == "1:1"


def test_subject_constraints_fold_into_prompt():
    p = PromptComposer().compose(
        Subject(
            text="a mountain",
            constraints=["side view", "transparent background"],
        )
    )
    assert p.startswith("a mountain, side view, transparent background --ar")


def test_full_style_stack_includes_all_flags():
    clear()
    p = PromptComposer().compose(
        Subject(text="a mountain"),
        style=StyleStack(
            moodboard="m1234567890123456789",
            sref="https://cdn.midjourney.com/x/0_0.png",
            stylize=50,
        ),
        aspect_ratio="16:9",
    )
    assert "--ar 16:9" in p
    assert "--v 7" in p
    assert "--style raw" in p
    assert "--p m1234567890123456789" in p
    assert "--sref https://cdn.midjourney.com/x/0_0.png" in p
    assert "--s 50" in p
    rec = snapshot()[-1]
    assert set(rec["payload"]["prompt_parts_used"]) == {"moodboard", "sref", "stylize"}


def test_style_weight_emits_sw_with_sref():
    clear()
    p = PromptComposer().compose(
        Subject(text="a mountain"),
        style=StyleStack(sref="https://cdn/s.png", sw=250),
    )
    assert "--sref https://cdn/s.png" in p
    assert "--sw 250" in p
    assert "sw" in snapshot()[-1]["payload"]["prompt_parts_used"]


def test_style_weight_without_sref_rejected_at_construction():
    """--sw only weights a style reference; setting it without sref is a no-op at
    Midjourney, so it's rejected where the consumer built it."""
    with pytest.raises(ValueError, match="only meaningful with a style reference"):
        StyleStack(sw=250)  # no sref


def test_style_weight_range_validated():
    for bad in (-1, 1001):
        with pytest.raises(ValueError, match="--sw range"):
            StyleStack(sref="https://cdn/s.png", sw=bad)
    StyleStack(sref="https://cdn/s.png", sw=0)
    StyleStack(sref="https://cdn/s.png", sw=1000)


def test_exp_emits_flag_and_validates_range():
    clear()
    p = PromptComposer().compose(
        Subject(text="a mountain"),
        params=ParamStack(exp=25),
    )
    assert "--exp 25" in p
    assert "exp" in snapshot()[-1]["payload"]["prompt_parts_used"]
    for bad in (-1, 101):
        with pytest.raises(ValueError, match="--exp range"):
            ParamStack(exp=bad)
    ParamStack(exp=0)
    ParamStack(exp=100)


def test_identity_stack_appends_oref_and_ow():
    clear()
    p = PromptComposer().compose(
        Subject(text="the same icon at a new angle"),
        style=StyleStack(moodboard="m1", sref="https://cdn/x.png"),
        identity=IdentityStack(oref="https://cdn/oref.png", ow=1000),
    )
    assert "--oref https://cdn/oref.png" in p
    assert "--ow 1000" in p
    rec = snapshot()[-1]
    assert "oref" in rec["payload"]["prompt_parts_used"]
    assert "ow" in rec["payload"]["prompt_parts_used"]


def test_identity_without_oref_is_noop():
    """An IdentityStack with oref=None should not add oref/ow flags."""
    p = PromptComposer().compose(
        Subject(text="x"),
        identity=IdentityStack(oref=None, ow=500),
    )
    assert "--oref" not in p
    assert "--ow" not in p


def test_style_raw_can_be_disabled():
    p = PromptComposer().compose(
        Subject(text="x"),
        style=StyleStack(style_raw=False),
    )
    assert "--style raw" not in p


def test_no_style_stack_still_emits_style_raw():
    """When style is None entirely, default behavior still applies --style raw
    (the safe default for cascade-img's locked-style use case)."""
    p = PromptComposer().compose(Subject(text="x"))
    assert "--style raw" in p


def test_subject_rejects_empty_text():
    """Subject.text='' or whitespace would otherwise render a subject-less
    prompt. Validated at construction so the bad
    Subject never reaches the composer."""
    import pytest as _pytest

    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="")
    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="   \t  ")
    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="\n")


def test_negatives_emit_single_no_clause():
    clear()
    p = PromptComposer().compose(
        Subject(text="a mountain", negatives=["text", "watermark", "human hands"])
    )
    # One --no clause, comma-joined, and it is the final flag (the bridge's
    # routing-token merge depends on --no being last).
    assert p.count("--no") == 1
    assert p.rstrip().endswith("--no text, watermark, human hands")
    rec = snapshot()[-1]
    assert rec["tag"] == "PROMPT_COMPOSED"
    assert "negatives" in rec["payload"]["prompt_parts_used"]


def test_param_stack_flags_and_signal():
    clear()
    p = PromptComposer().compose(
        Subject(text="x"),
        params=ParamStack(tile=True, chaos=50, weird=250, quality=2, seed=12345),
    )
    for frag in ["--tile", "--chaos 50", "--weird 250", "--q 2", "--seed 12345"]:
        assert frag in p
    used = set(snapshot()[-1]["payload"]["prompt_parts_used"])
    assert {"tile", "chaos", "weird", "quality", "seed"} <= used


def test_param_stack_validates_ranges_at_construction():
    for kw in (
        {"chaos": 150},
        {"chaos": -1},
        {"weird": 3001},
        {"quality": 3},
        {"seed": 4294967296},
    ):
        with pytest.raises(ValueError):
            ParamStack(**kw)
    # boundaries accepted
    ParamStack(chaos=0)
    ParamStack(chaos=100)
    ParamStack(weird=3000)
    ParamStack(quality=4)
    ParamStack(seed=0)
    ParamStack(seed=4294967295)


def test_image_prompts_lead_prompt_with_iw():
    clear()
    p = PromptComposer().compose(
        Subject(
            text="a mountain",
            image_prompts=["https://cdn/ref1.png", "https://cdn/ref2.png"],
            image_weight=2.0,
        )
    )
    assert p.startswith("https://cdn/ref1.png https://cdn/ref2.png a mountain")
    assert "--iw 2.0" in p
    used = set(snapshot()[-1]["payload"]["prompt_parts_used"])
    assert {"image_prompt", "image_weight"} <= used


def test_image_weight_requires_image_prompts_and_range():
    with pytest.raises(ValueError, match="image_weight"):
        Subject(text="x", image_weight=1.5)  # no image_prompts
    with pytest.raises(ValueError, match="0-3"):
        Subject(text="x", image_prompts=["https://cdn/a.png"], image_weight=4.0)


def test_stylize_and_ow_validated_at_construction():
    """StyleStack.stylize and IdentityStack.ow advertise 0-1000 validation;
    prove the boundary raises and the endpoints are accepted."""
    for bad in (-1, 1001):
        with pytest.raises(ValueError, match="--s range"):
            StyleStack(stylize=bad)
        with pytest.raises(ValueError, match="--ow range"):
            IdentityStack(ow=bad)
    StyleStack(stylize=0)
    StyleStack(stylize=1000)
    IdentityStack(ow=0)
    IdentityStack(ow=1000)


def test_multi_part_prompt_keeps_no_clause_last():
    clear()
    p = PromptComposer().compose(
        Subject(text="a mountain", negatives=["text"]),
        style=StyleStack(moodboard="m1", stylize=50),
        params=ParamStack(chaos=10, seed=7),
    )
    assert p.rstrip().endswith("--no text")

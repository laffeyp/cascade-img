"""Behavior contract for PromptComposer.

Validates the v7 prompt-string assembly across the four facet combinations
the consumer can build, plus the signal payload on each.
"""

from __future__ import annotations

from cascade_img.composer import (
    IdentityStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.vocabulary import clear, snapshot


def test_subject_only_emits_minimal_prompt():
    clear()
    p = PromptComposer().compose(Subject(text="a small finch"))
    # No moodboard, no sref, no oref. style_raw default-on.
    assert p == "a small finch --ar 1:1 --v 7 --style raw"
    rec = snapshot()[-1]
    assert rec["tag"] == "PROMPT_COMPOSED"
    assert rec["payload"]["prompt_parts_used"] == []
    assert rec["payload"]["aspect_ratio"] == "1:1"


def test_subject_constraints_fold_into_prompt():
    p = PromptComposer().compose(
        Subject(
            text="a small finch",
            constraints=["side view", "transparent background"],
        )
    )
    assert p.startswith("a small finch, side view, transparent background --ar")


def test_full_style_stack_includes_all_flags():
    clear()
    p = PromptComposer().compose(
        Subject(text="a small finch"),
        style=StyleStack(moodboard="m7458053701014388751", sref="https://cdn.midjourney.com/x/0_0.png", stylize=50),
        aspect_ratio="16:9",
    )
    assert "--ar 16:9" in p
    assert "--v 7" in p
    assert "--style raw" in p
    assert "--p m7458053701014388751" in p
    assert "--sref https://cdn.midjourney.com/x/0_0.png" in p
    assert "--s 50" in p
    rec = snapshot()[-1]
    assert set(rec["payload"]["prompt_parts_used"]) == {"moodboard", "sref", "stylize"}


def test_identity_stack_appends_oref_and_ow():
    clear()
    p = PromptComposer().compose(
        Subject(text="the same finch with its wings raised"),
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
    prompt (review-003 MEDIUM). Validated at construction so the bad
    Subject never reaches the composer."""
    import pytest as _pytest
    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="")
    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="   \t  ")
    with _pytest.raises(ValueError, match="non-empty description"):
        Subject(text="\n")

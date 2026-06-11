"""Vocabulary-validation contract for the event-emit module.

The schema is enforced at emit time: an unknown tag raises, a missing required
field raises. The assert_signal / assert_no_signal helpers are the test
primitives for asserting which events a code path emits.
"""

from __future__ import annotations

import pytest

from cascade_img.vocabulary import (
    Emitter,
    assert_no_signal,
    assert_signal,
    clear,
    emit,
    format_for_ai,
    vocabulary,
)


def test_vocabulary_loads_from_package_data():
    v = vocabulary()
    assert v.version == "0.1"
    assert v.locked is True
    # Pin the exact count: a tag added or dropped without updating the catalog
    # (or a regression that loses tags) fails loudly here. Bump with the lock.
    # 48 since 2026-06-06 (Wave N): UPSCALE_DOWNLOAD_DROPPED added in-place
    # (pre-release living vocabulary; no version bump per Architect direction).
    assert len(v.tags()) == 48
    assert "CASCADE_INIT" in v.tags()
    assert "UPSCALE_DOWNLOAD_DROPPED" in v.tags()


def test_unknown_tag_raises_at_emit():
    clear()
    with pytest.raises(ValueError, match="Unknown event tag 'NOT_A_REAL_TAG'"):
        emit("NOT_A_REAL_TAG", asset_id="x")


def test_missing_required_field_raises():
    clear()
    # CASCADE_INIT requires [package_version, backend]
    with pytest.raises(ValueError, match="missing required payload fields"):
        emit("CASCADE_INIT", package_version="x")  # missing backend


def test_undeclared_payload_field_raises():
    """The schema's ``validator-extras: strict`` posture must be enforced:
    payload keys that aren't in the tag's ``payload`` or ``optional_payload``
    raise at emit time. Without this check the strictness guarantee was a
    lie."""
    clear()
    with pytest.raises(ValueError, match="undeclared payload fields"):
        emit(
            "CASCADE_INIT",
            package_version="0.1.0",
            backend="midjourney_discord",
            bogus_extra_field="shouldnt-be-allowed",
        )


def test_out_of_enum_value_raises():
    """A field with an evidence-constraint enum must carry a declared value;
    an out-of-contract value (here a bad action_kind) raises at emit. Without
    this the evidence constraints were a dead letter — shape was checked, values
    were not."""
    clear()
    with pytest.raises(ValueError, match="outside its locked enum"):
        emit(
            "MJ_DERIVED_RECEIVED",
            asset_id="a",
            job_id="j",
            parent_message_id=1,
            action_kind="teleport",  # not in [variation, zoom, pan, upscale, animation]
            mj_uuid="u",
            path="/p",
            bytes=1,
            content_type="image/webp",
        )


def test_in_enum_value_passes():
    """The same tag with a declared action_kind emits cleanly."""
    clear()
    emit(
        "MJ_DERIVED_RECEIVED",
        asset_id="a",
        job_id="j",
        parent_message_id=1,
        action_kind="animation",
        mj_uuid="u",
        path="/p",
        bytes=1,
        content_type="image/webp",
    )
    assert assert_signal("MJ_DERIVED_RECEIVED")["payload"]["action_kind"] == "animation"


def test_assert_signal_returns_matching_record():
    clear()
    emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    rec = assert_signal("CASCADE_INIT")
    assert rec["tag"] == "CASCADE_INIT"
    assert rec["payload"]["backend"] == "midjourney_discord"


def test_assert_signal_partial_payload_match():
    clear()
    emit("IMAGINE_FIRED", asset_id="mountain-icon", job_id="abc", prompt_chars=100, upscale="1")
    emit("IMAGINE_FIRED", asset_id="hero-portrait", job_id="def", prompt_chars=80, upscale=None)
    rec = assert_signal("IMAGINE_FIRED", asset_id="hero-portrait")
    assert rec["payload"]["job_id"] == "def"


def test_assert_signal_raises_when_missing():
    clear()
    with pytest.raises(AssertionError, match="expected event 'CASCADE_INIT'"):
        assert_signal("CASCADE_INIT")


def test_assert_no_signal_passes_when_absent():
    clear()
    emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    assert_no_signal("JOB_FAILED")  # absent — passes


def test_assert_no_signal_raises_when_present():
    clear()
    emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    with pytest.raises(AssertionError, match="expected no 'CASCADE_INIT'"):
        assert_no_signal("CASCADE_INIT")


def test_format_for_ai_groups_by_category():
    clear()
    emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp", has_guild_id=False)
    out = format_for_ai(context="QA: boot sequence")
    assert "## Event Capture" in out
    assert "Context: QA: boot sequence" in out
    assert "Vocabulary: 0.1" in out
    assert "### session" in out  # CASCADE_INIT's category
    assert "### config" in out  # CONFIG_VALIDATED's category
    assert "CASCADE_INIT" in out
    assert "CONFIG_VALIDATED" in out


def test_strict_mode_can_be_disabled_per_emitter():
    """An emitter with strict=False does not raise on unknown tags."""
    v = vocabulary()
    e = Emitter(v, strict=False)
    sig = e.emit("NOT_A_REAL_TAG", x=1)
    assert sig.tag == "NOT_A_REAL_TAG"
    assert sig.category == "unknown"


def test_signal_record_carries_t_and_wall_ts():
    clear()
    sig = emit("CASCADE_INIT", package_version="0.1.0a1", backend="midjourney_discord")
    assert "t" in sig
    assert sig["t"] >= 0
    assert "ts" in sig
    assert sig["vocab_version"] == "0.1"

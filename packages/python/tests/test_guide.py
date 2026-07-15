"""Tests for the packaged operator guide loader (Sprint 026)."""

from __future__ import annotations

import pytest

from cascade_img.guide import guide_sections, load_guide


def test_full_corpus_loads_nonempty_multi_doc():
    s = load_guide()
    # The full manual is large and carries several docs — the injection payload.
    assert len(s) > 60000
    assert "RUNBOOK" in s
    assert "CAPABILITIES" in s
    # AGENTS content is present (its section header and a tool name).
    assert "compose_prompt" in s


def test_section_returns_single_doc():
    caps = load_guide("CAPABILITIES")
    assert caps.strip()
    # A single section is a strict subset of the whole corpus.
    assert len(caps) < len(load_guide())


def test_unknown_section_raises():
    with pytest.raises(ValueError):
        load_guide("nope")


def test_sections_listed_in_reading_order():
    keys = guide_sections()
    assert keys[0] == "AGENTS"
    assert "CAPABILITIES" in keys
    assert keys[-1] == "AGENT_RUNDOWN"

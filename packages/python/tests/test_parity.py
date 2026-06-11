"""Parity contract: every emit() in the package uses a vocabulary tag.

This is the same check the standalone tool runs, lifted into pytest so a
failing parity is a failing test — the CI gate uses it without any
shell-level orchestration.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# tools/ lives at the engine package root; surface it before importing the
# parity checker. `noqa: E402` because the path-insert must precede the import.
PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT / "tools"))

import check_vocabulary_parity  # type: ignore  # noqa: E402


@pytest.mark.contract
def test_parity_clean():
    rc = check_vocabulary_parity.main([])
    assert rc == 0, "vocabulary parity drift — see stdout for the offending emit() callsites"


@pytest.mark.contract
def test_stored_tag_set_hash_matches_catalog():
    """The committed tag_set_hash must equal the recomputed hash — the real
    catalog passes its own lock-integrity check."""
    data = json.loads(
        (PKG_ROOT / "src/cascade_img/vocabulary/versions/0.1.json").read_text(encoding="utf-8")
    )
    assert data["tag_set_hash"] == check_vocabulary_parity.compute_tag_set_hash(data)


@pytest.mark.contract
def test_tag_set_hash_detects_unacknowledged_mutation(tmp_path):
    """A tag added without updating tag_set_hash fails the parity check. Mutate a
    COPY so the real catalog is untouched (the card's no-commit mutation probe)."""
    data = json.loads(
        (PKG_ROOT / "src/cascade_img/vocabulary/versions/0.1.json").read_text(encoding="utf-8")
    )
    data["tags"].append(
        {"name": "ZZ_FAKE_TAG", "category": "job", "stratum": "event", "payload": ["x"]}
    )
    mutated = tmp_path / "0.1.json"
    mutated.write_text(json.dumps(data), encoding="utf-8")
    rc = check_vocabulary_parity.main(["--vocab", str(mutated), "--src", "src/cascade_img"])
    assert rc == 1, "a tag added without updating tag_set_hash should fail parity"


@pytest.mark.contract
def test_reference_doc_matches_fresh_render():
    """vocabulary/0.1-reference.md must equal a fresh render of the catalog, so a
    catalog change that forgets to regenerate the reference fails here with a fix
    instruction — same posture as the tag_set_hash check. Uses the renderer's own
    VOCAB_PATH/REFERENCE_PATH constants (repo-root resolution lives in the tool)."""
    import render_vocabulary_reference as rvr

    vocab = json.loads(rvr.VOCAB_PATH.read_text(encoding="utf-8"))
    committed = rvr.REFERENCE_PATH.read_text(encoding="utf-8")
    assert committed == rvr.render_reference(vocab), (
        "vocabulary/0.1-reference.md is stale: regenerate with "
        "`python3.14 tools/render_vocabulary_reference.py`"
    )

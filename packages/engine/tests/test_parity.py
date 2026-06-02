"""Parity contract: every emit() in the package uses a vocabulary tag.

This is the same check the standalone tool runs, lifted into pytest so a
failing parity is a failing test — the CI gate uses it without any
shell-level orchestration.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Make the tools/ module importable
PKG_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PKG_ROOT / "tools"))

import check_vocabulary_parity  # type: ignore


def test_parity_clean():
    rc = check_vocabulary_parity.main([])
    assert rc == 0, "vocabulary parity drift — see stdout for the offending emit() callsites"

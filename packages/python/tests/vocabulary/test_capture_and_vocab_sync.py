"""Coverage for the kit-conformant ``capture()`` context manager and the
project-root vocabulary mirror.

Both items surfaced in the 2026-06-02 external review:

* ``capture()`` was exported from sdd.py but had no test (reviewer-flagged).
* ``signals/0.1.json`` at project root must remain identical to the
  package-bundled ``packages/python/src/cascade_img/vocabulary/versions/0.1.json``
  (the runtime canonical). A divergence test catches drift before it ships.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from cascade_img.vocabulary import (
    capture,
    emit,
    snapshot,
)

# --------------- capture() ---------------


def test_capture_clears_at_enter():
    # Pre-pollute the buffer so we can prove enter clears it.
    emit("CASCADE_INIT", package_version="x", backend="x")
    assert len(snapshot()) >= 1

    with capture(context="QA: enter-clears") as emitter:
        # Buffer empty on entry.
        assert emitter.snapshot() == []
        emit("CONFIG_VALIDATED", port=5000, output_dir="/tmp", has_guild_id=False)
        assert len(emitter.snapshot()) == 1


def test_capture_leaves_buffer_intact_at_exit():
    """Per docstring (corrected 2026-06-02): buffer is NOT cleared at exit so
    the caller can inspect/format/assert after the block."""
    with capture():
        emit("CASCADE_INIT", package_version="x", backend="x")
    # After block: records still readable.
    records = snapshot()
    assert len(records) == 1
    assert records[0]["tag"] == "CASCADE_INIT"


def test_capture_yields_module_emitter():
    """The emitter yielded inside the block is the module-level singleton —
    same snapshot() works inside and out."""
    with capture() as emitter:
        emit("CASCADE_INIT", package_version="x", backend="x")
        assert len(emitter.snapshot()) == 1
        assert len(snapshot()) == 1


def test_capture_with_context_in_format_for_ai():
    with capture(context="QA: feature X") as emitter:
        emit("CASCADE_INIT", package_version="x", backend="x")
        out = emitter.format_for_ai(context="QA: feature X")
    assert "Context: QA: feature X" in out
    assert "CASCADE_INIT" in out


# --------------- vocabulary file sync ---------------


@pytest.mark.contract
def test_root_and_package_vocab_files_are_identical():
    """The project-root ``vocabulary/0.1.json`` must match the package-data
    copy at ``packages/python/src/cascade_img/vocabulary/versions/0.1.json``.
    """
    # tests/vocabulary/<this> -> tests/ -> packages/python/
    pkg_root = Path(__file__).resolve().parents[2]
    repo_root = pkg_root.parents[1]
    root_vocab = repo_root / "vocabulary" / "0.1.json"
    pkg_vocab = pkg_root / "src" / "cascade_img" / "vocabulary" / "versions" / "0.1.json"
    if not root_vocab.exists():
        # In a source checkout (src/ present) the mirror MUST exist — a missing
        # file is real drift, not the installed-wheel case. Fail loudly there;
        # skip only when running against an installed wheel.
        if (pkg_root / "src").is_dir():
            pytest.fail(
                "Project-root vocabulary/0.1.json is missing in a source checkout "
                "— the byte-identical mirror was moved or deleted."
            )
        pytest.skip(
            "Project-root vocabulary/0.1.json not present (running against an installed wheel)."
        )
    assert json.loads(root_vocab.read_text()) == json.loads(pkg_vocab.read_text()), (
        "vocabulary/0.1.json at project root has diverged from the package-data copy."
    )

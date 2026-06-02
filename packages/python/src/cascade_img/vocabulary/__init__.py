"""Structured runtime events.

Every state transition in cascade-img emits a tagged record (tag + payload +
timestamps) that consumers read to understand what the program did. Tags are
validated against a locked vocabulary at emit time — unknown tags raise,
missing required payload fields raise — so traces can't drift silently from
the documented contract.

The vocabulary itself lives at ``cascade_img/vocabulary/versions/0.1.json``
and is loaded once at import. Set ``CASCADE_STRICT_SIGNALS=false`` to
disable emit-time validation in production.
"""

from cascade_img.vocabulary._runtime import (
    VOCAB_VERSION,
    Emitter,
    Signal,
    Vocabulary,
    assert_no_signal,
    assert_signal,
    capture,
    clear,
    emit,
    flush_to_file,
    format_for_ai,
    snapshot,
    vocabulary,
)

__all__ = [
    "VOCAB_VERSION",
    "Emitter",
    "Signal",
    "Vocabulary",
    "assert_no_signal",
    "assert_signal",
    "capture",
    "clear",
    "emit",
    "flush_to_file",
    "format_for_ai",
    "snapshot",
    "vocabulary",
]

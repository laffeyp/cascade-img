"""SDD instrumentation runtime for cascade-img.

The :mod:`cascade_img.instrumentation.sdd` module exports :func:`emit`,
:func:`snapshot`, :func:`flush_to_file`, and :func:`clear`. The locked
vocabulary lives at ``cascade_img/signals/versions/0.1.json``; the parity
tool reads both and asserts every emitted tag exists in the vocabulary.
"""

from cascade_img.instrumentation.sdd import (
    VOCAB_VERSION,
    clear,
    emit,
    flush_to_file,
    snapshot,
)

__all__ = ["VOCAB_VERSION", "clear", "emit", "flush_to_file", "snapshot"]

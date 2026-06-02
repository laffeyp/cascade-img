"""the event system instrumentation runtime for cascade-img.

The :mod:`cascade_img.instrumentation.runtime` module exports :func:`emit`,
:func:`snapshot`, :func:`flush_to_file`, and :func:`clear`. The locked
vocabulary lives at ``cascade_img/signals/versions/0.1.json``; the parity
tool reads both and asserts every emitted tag exists in the vocabulary.
"""

from cascade_img.instrumentation.runtime import (
    VOCAB_VERSION,
    clear,
    emit,
    flush_to_file,
    snapshot,
)

__all__ = ["emit", "snapshot", "flush_to_file", "clear", "VOCAB_VERSION"]

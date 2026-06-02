"""event-driven development instrumentation for cascade-img.

Port of ``the toolkit/lib/sdd.py``. The kit's discipline says schema enforced at
emit time (per ``the design notes``): unknown tags
raise, missing required payload fields raise. The vocabulary is the contract;
emit() validates against it.

Loaded once at import: the package-bundled ``signals/versions/0.1.json`` is
parsed into a :class:`SignalVocabulary`. The module-level :func:`emit`,
:func:`snapshot`, :func:`clear`, :func:`flush_to_file`, :func:`assert_signal`,
:func:`assert_no_signal`, and :func:`format_for_ai` operate against the
default emitter.

The strict-validation default may be relaxed in production by setting
``CASCADE_STRICT_SIGNALS=false`` in the environment — useful when a drift
makes its way to a deployed daemon and you want it to keep running while the
vocabulary catches up. Drift is still a defect; the env var is a release
valve, not a permission slip.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from threading import Lock
from typing import Any, Iterator, Optional

VOCAB_VERSION = "0.1"


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------


class SignalVocabulary:
    """The stable, typed API of things cascade-img can say.

    Loaded from the locked JSON at ``cascade_img/signals/versions/0.1.json``.
    Schema shape matches the kit's:

        {
          "vocabulary_version": "0.1",
          "locked": true,
          "categories": [...],
          "tags": [
            {"name": "TAG", "category": "...", "stratum": "...",
             "payload": ["required_field", ...], "note": "..."},
            ...
          ]
        }
    """

    def __init__(self, schema: dict[str, Any]):
        self._raw = schema
        self.version: str = schema.get("vocabulary_version", "unknown")
        self.locked: bool = bool(schema.get("locked", False))
        self.categories: list[str] = list(schema.get("categories", []))
        self._tag_index: dict[str, dict[str, Any]] = {
            t["name"]: t for t in schema.get("tags", [])
        }

    @classmethod
    def from_package_data(cls) -> "SignalVocabulary":
        """Load the vocabulary bundled inside the cascade_img package."""
        ref = files("cascade_img.signals.versions") / "0.1.json"
        with ref.open("r", encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_path(cls, path: Path | str) -> "SignalVocabulary":
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self, tag: str, payload: dict[str, Any]) -> None:
        """Raise on unknown tag or missing required field."""
        spec = self._tag_index.get(tag)
        if spec is None:
            raise ValueError(
                f"Unknown signal tag '{tag}'. Define it in signals/versions/"
                f"{self.version}.json before emitting, or extend the "
                f"vocabulary via the change proposal "
                f"taxonomy in the toolkit/the design notes."
            )
        required = spec.get("payload", []) or []
        missing = [f for f in required if f not in payload]
        if missing:
            raise ValueError(
                f"Signal '{tag}' missing required payload fields: {missing}. "
                f"Required by vocabulary: {required}"
            )

    def category_of(self, tag: str) -> str:
        return self._tag_index[tag]["category"]

    def stratum_of(self, tag: str) -> str:
        return self._tag_index[tag].get("stratum", "event")

    def tags(self) -> list[str]:
        return list(self._tag_index.keys())


# ---------------------------------------------------------------------------
# Signal record
# ---------------------------------------------------------------------------


@dataclass
class Signal:
    tag: str
    category: str
    stratum: str
    payload: dict[str, Any]
    t: float  # seconds since session start (time.monotonic delta)
    wall_ts: float = field(default_factory=time.time)  # wall-clock for JSONL

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "category": self.category,
            "stratum": self.stratum,
            "t": round(self.t, 4),
            "ts": self.wall_ts,
            "vocab_version": VOCAB_VERSION,
            "payload": dict(self.payload),
        }


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------


class SignalEmitter:
    """Validates against the vocabulary at emit time. Thread-safe."""

    def __init__(
        self,
        vocabulary: SignalVocabulary,
        max_buffer: int = 5000,
        strict: bool = True,
    ):
        self._vocab = vocabulary
        self._buffer: deque[Signal] = deque(maxlen=max_buffer)
        self._lock = Lock()
        self._session_start = time.monotonic()
        self.strict = strict

    def emit(self, tag: str, **payload: Any) -> Signal:
        if self.strict:
            self._vocab.validate(tag, payload)
        # In non-strict mode, unknown tag still gets a default category.
        try:
            cat = self._vocab.category_of(tag)
            stratum = self._vocab.stratum_of(tag)
        except KeyError:
            cat = "unknown"
            stratum = "event"

        signal = Signal(
            tag=tag,
            category=cat,
            stratum=stratum,
            payload=dict(payload),
            t=time.monotonic() - self._session_start,
        )
        with self._lock:
            self._buffer.append(signal)
        return signal

    def snapshot(self) -> list[Signal]:
        with self._lock:
            return list(self._buffer)

    def clear(self) -> None:
        with self._lock:
            self._buffer.clear()
        self._session_start = time.monotonic()

    def flush_to_file(self, path: Path | str) -> int:
        records = self.snapshot()
        Path(path).write_text(
            "\n".join(json.dumps(r.to_dict()) for r in records)
            + ("\n" if records else ""),
            encoding="utf-8",
        )
        return len(records)

    def format_for_ai(self, context: str = "") -> str:
        """Compact human/LLM-readable digest of the buffer, grouped by
        category. Matches the kit reference's ``format_for_ai`` shape so
        captures from cascade-img look like captures from any kit-conformant
        project."""
        records = self.snapshot()
        lines: list[str] = ["## Signal Capture"]
        if context:
            lines.append(f"Context: {context}")
        lines.append(f"Vocabulary: {self._vocab.version}")
        lines.append(f"Total signals: {len(records)}")
        lines.append("")
        by_cat: dict[str, list[Signal]] = {}
        for s in records:
            by_cat.setdefault(s.category, []).append(s)
        for cat, ss in by_cat.items():
            lines.append(f"### {cat}")
            for s in ss:
                payload_str = "  ".join(f"{k}={v}" for k, v in s.payload.items())
                lines.append(f"  t={s.t:.3f}  {s.tag}  {payload_str}")
            lines.append("")
        return "\n".join(lines)

    def assert_signal(self, tag: str, **partial_payload: Any) -> Signal:
        """Test primitive (kit Section 1 technique #38). Returns the first
        matching record, raises AssertionError if none."""
        for s in self.snapshot():
            if s.tag != tag:
                continue
            if all(s.payload.get(k) == v for k, v in partial_payload.items()):
                return s
        raise AssertionError(
            f"expected signal {tag!r}{(' with ' + str(partial_payload)) if partial_payload else ''}; "
            f"got tags: {[s.tag for s in self.snapshot()]}"
        )

    def assert_no_signal(self, tag: str) -> None:
        for s in self.snapshot():
            if s.tag == tag:
                raise AssertionError(
                    f"expected no {tag!r} but found one at t={s.t:.3f} payload={s.payload}"
                )


# ---------------------------------------------------------------------------
# Module-level default emitter
# ---------------------------------------------------------------------------

_STRICT = os.environ.get("CASCADE_STRICT_SIGNALS", "true").lower() not in ("0", "false", "no")
_VOCAB = SignalVocabulary.from_package_data()
_EMITTER = SignalEmitter(_VOCAB, strict=_STRICT)


def emit(tag: str, **payload: Any) -> dict[str, Any]:
    """Append a signal to the in-process buffer; return its dict form."""
    return _EMITTER.emit(tag, **payload).to_dict()


def snapshot() -> list[dict[str, Any]]:
    return [s.to_dict() for s in _EMITTER.snapshot()]


def clear() -> None:
    _EMITTER.clear()


def flush_to_file(path: Path | str) -> int:
    return _EMITTER.flush_to_file(path)


def format_for_ai(context: str = "") -> str:
    return _EMITTER.format_for_ai(context=context)


def assert_signal(tag: str, **partial_payload: Any) -> dict[str, Any]:
    return _EMITTER.assert_signal(tag, **partial_payload).to_dict()


def assert_no_signal(tag: str) -> None:
    _EMITTER.assert_no_signal(tag)


def vocabulary() -> SignalVocabulary:
    return _VOCAB


@contextmanager
def capture(context: str = "") -> Iterator["SignalEmitter"]:
    """Context manager for a bounded signal session.

    Clears the buffer at enter and exit so the captured slice is scoped to
    the with-block. Yields the emitter so callers can format/assert against
    it without referencing the module-level singleton.
    """
    clear()
    try:
        yield _EMITTER
    finally:
        # Intentionally NOT clearing on exit — the caller may want to inspect
        # the buffer after the block. Re-enter clears again.
        pass

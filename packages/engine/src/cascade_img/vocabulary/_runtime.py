"""Implementation of the vocabulary runtime.

The public surface is re-exported from :mod:`cascade_img.vocabulary`; this
module exists so the package directory can also hold the versioned JSON
under ``versions/``. Consumers should not import from here directly.
"""

from __future__ import annotations

import json
import os
import time
from collections import deque
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from importlib.resources import files
from pathlib import Path
from threading import Lock
from typing import Any

VOCAB_VERSION = "0.1"


class Vocabulary:
    """The set of tags the program is allowed to emit.

    Loaded from ``cascade_img/vocabulary/versions/0.1.json``. Schema:

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
        self._tag_index: dict[str, dict[str, Any]] = {t["name"]: t for t in schema.get("tags", [])}

    @classmethod
    def from_package_data(cls) -> Vocabulary:
        """Load the vocabulary bundled inside the cascade_img package."""
        ref = files("cascade_img.vocabulary.versions") / "0.1.json"
        with ref.open("r", encoding="utf-8") as f:
            return cls(json.load(f))

    @classmethod
    def from_path(cls, path: Path | str) -> Vocabulary:
        return cls(json.loads(Path(path).read_text(encoding="utf-8")))

    def validate(self, tag: str, payload: dict[str, Any]) -> None:
        """Raise on unknown tag, missing required field, or undeclared field.

        Enforces the ``validator-extras: strict`` posture the schema declares
        in ``grammar_growth.project_overrides``: every payload key must be in
        the tag's ``payload`` (required) or ``optional_payload`` (allowed-
        optional) list. Production may relax the extras check by setting
        ``CASCADE_STRICT_SIGNALS=false`` on the emitter (see :class:`Emitter`).
        """
        spec = self._tag_index.get(tag)
        if spec is None:
            raise ValueError(
                f"Unknown event tag {tag!r}. Add it to "
                f"vocabulary/versions/{self.version}.json before emitting."
            )
        required = spec.get("payload", []) or []
        missing = [f for f in required if f not in payload]
        if missing:
            raise ValueError(
                f"Event {tag!r} missing required payload fields: {missing}. "
                f"Required by vocabulary: {required}"
            )
        optional = spec.get("optional_payload", []) or []
        allowed = set(required) | set(optional)
        extra = [k for k in payload if k not in allowed]
        if extra:
            raise ValueError(
                f"Event {tag!r} has undeclared payload fields: {extra}. "
                f"Declared by vocabulary: required={required}, optional={optional}. "
                f"Add them to vocabulary/versions/{self.version}.json or "
                f"drop them from the emit call."
            )

    def category_of(self, tag: str) -> str:
        return self._tag_index[tag]["category"]

    def stratum_of(self, tag: str) -> str:
        return self._tag_index[tag].get("stratum", "event")

    def tags(self) -> list[str]:
        return list(self._tag_index.keys())


@dataclass
class Signal:
    """One emitted record.

    Carries ``vocab_version`` so the record reflects the vocabulary that
    actually emitted it, not the module-global. Matters once a process
    loads more than one vocabulary version (uncommon today but a latent
    bug otherwise — review-003 LOW).
    """

    tag: str
    category: str
    stratum: str
    payload: dict[str, Any]
    t: float  # seconds since session start (time.monotonic delta)
    wall_ts: float = field(default_factory=time.time)  # wall-clock timestamp
    vocab_version: str = VOCAB_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "tag": self.tag,
            "category": self.category,
            "stratum": self.stratum,
            "t": round(self.t, 4),
            "ts": self.wall_ts,
            "vocab_version": self.vocab_version,
            "payload": dict(self.payload),
        }


class Emitter:
    """Validates against the vocabulary at emit time. Thread-safe."""

    def __init__(
        self,
        vocabulary: Vocabulary,
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
            vocab_version=self._vocab.version,
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
            "\n".join(json.dumps(r.to_dict()) for r in records) + ("\n" if records else ""),
            encoding="utf-8",
        )
        return len(records)

    def format_for_ai(self, context: str = "") -> str:
        """Compact text digest of the buffer, grouped by category."""
        records = self.snapshot()
        lines: list[str] = ["## Event Capture"]
        if context:
            lines.append(f"Context: {context}")
        lines.append(f"Vocabulary: {self._vocab.version}")
        lines.append(f"Total events: {len(records)}")
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
        """Return the first record matching ``tag`` (and any partial payload
        keys/values). Raise :class:`AssertionError` if none match."""
        for s in self.snapshot():
            if s.tag != tag:
                continue
            if all(s.payload.get(k) == v for k, v in partial_payload.items()):
                return s
        raise AssertionError(
            f"expected event {tag!r}"
            f"{(' with ' + str(partial_payload)) if partial_payload else ''}; "
            f"got tags: {[s.tag for s in self.snapshot()]}"
        )

    def assert_no_signal(self, tag: str) -> None:
        for s in self.snapshot():
            if s.tag == tag:
                raise AssertionError(
                    f"expected no {tag!r} but found one at t={s.t:.3f} payload={s.payload}"
                )


_STRICT = os.environ.get("CASCADE_STRICT_SIGNALS", "true").lower() not in ("0", "false", "no")
_VOCAB = Vocabulary.from_package_data()
_EMITTER = Emitter(_VOCAB, strict=_STRICT)


def emit(tag: str, **payload: Any) -> dict[str, Any]:
    """Append an event to the in-process buffer; return its dict form."""
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


def vocabulary() -> Vocabulary:
    return _VOCAB


@contextmanager
def capture(context: str = "") -> Iterator[Emitter]:
    """Context manager that clears the buffer on enter and leaves it intact
    on exit, so callers can inspect, assert, or :func:`format_for_ai` the
    captured slice after the with-block."""
    clear()
    yield _EMITTER

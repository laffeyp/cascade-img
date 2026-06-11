"""Asset registry loader.

A registry is a JSON file mapping ``asset_id`` to its composable prompt parts:

.. code-block:: json

    {
      "mountain-icon": {
        "subject": "a flat-design icon of a mountain",
        "constraints": ["centered", "simple shapes", "transparent background"],
        "moodboard": "<optional moodboard code>",
        "sref": "<optional style-reference URL>",
        "aspect_ratio": "1:1",
        "oref": null,
        "ow": 100,
        "stylize": null
      }
    }

The loader validates the shape, fills defaults, and returns a dict keyed by
asset_id. Unknown keys are tolerated (forward-compatible) but logged.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _int_or_none(value: Any) -> int | None:
    """Coerce an optional numeric registry field to ``int | None``.

    ``sw`` and ``stylize`` reach the composer's ParamStack as ints; a string or
    float slipping through un-coerced (the loader previously passed them through
    raw, unlike ``ow``/``aspect_ratio``) would surface only when the composer or
    backend choked — crashing the CLI with a raw traceback instead of the
    structured ``CLI_ROLL_FAILED`` envelope. Coercing here means a malformed
    value raises at load time, where :func:`load_registry` already wraps it into
    a ``ValueError`` the CLI envelopes.
    """
    return None if value is None else int(value)


@dataclass
class AssetEntry:
    """One entry from the registry. ``subject`` is the only required field."""

    subject: str
    constraints: list[str] = field(default_factory=list)
    moodboard: str | None = None
    sref: str | None = None
    sw: int | None = None
    stylize: int | None = None
    style_raw: bool = True
    oref: str | None = None
    ow: int = 100
    aspect_ratio: str = "1:1"

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> AssetEntry:
        if "subject" not in raw or not raw["subject"]:
            raise ValueError("asset entry missing required 'subject'")
        return cls(
            subject=str(raw["subject"]),
            constraints=list(raw.get("constraints") or []),
            moodboard=raw.get("moodboard"),
            sref=raw.get("sref"),
            sw=_int_or_none(raw.get("sw")),
            stylize=_int_or_none(raw.get("stylize")),
            style_raw=bool(raw.get("style_raw", True)),
            oref=raw.get("oref"),
            ow=int(raw.get("ow", 100)),
            aspect_ratio=str(raw.get("aspect_ratio", "1:1")),
        )


def load_registry(path: str | Path) -> dict[str, AssetEntry]:
    """Load and validate a JSON registry. Raises FileNotFoundError if the
    path doesn't exist, ValueError on malformed entries."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"registry not found: {p}")
    raw = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"registry must be a JSON object; got {type(raw).__name__}")
    entries: dict[str, AssetEntry] = {}
    for asset_id, body in raw.items():
        if not isinstance(body, dict):
            raise ValueError(f"registry entry '{asset_id}' must be an object")
        try:
            entries[asset_id] = AssetEntry.from_dict(body)
        except Exception as e:
            raise ValueError(f"registry entry '{asset_id}': {e}") from e
    return entries

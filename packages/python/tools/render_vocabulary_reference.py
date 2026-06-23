#!/usr/bin/env python3
"""Render the per-tag vocabulary reference from the vocabulary JSON.

Reads ``vocabulary/0.1.json`` at the repo root and writes
``vocabulary/0.1-reference.md``: one entry per tag with its category,
payload fields, emitter, enum-constrained values, and when it fires.
The JSON stays the source of truth; the reference is generated, never
hand-edited.

Usage:
    python3 tools/render_vocabulary_reference.py            # regenerate
    python3 tools/render_vocabulary_reference.py --check    # CI: fail if stale
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VOCAB_PATH = REPO_ROOT / "vocabulary" / "0.1.json"
REFERENCE_PATH = REPO_ROOT / "vocabulary" / "0.1-reference.md"


def build_emitter_index(vocab: dict) -> dict[str, tuple[str, str]]:
    """Map tag name -> (operator name, source location)."""
    index: dict[str, tuple[str, str]] = {}
    for op in vocab["operators"]["operators"]:
        for tag in op["emits"]:
            index[tag] = (op["name"], op["location"])
    return index


def build_enum_index(vocab: dict) -> dict[str, list[tuple[str, list[str]]]]:
    """Map tag name -> [(field, allowed values), ...] from evidence constraints."""
    index: dict[str, list[tuple[str, list[str]]]] = {}
    for c in vocab["evidence_constraints"]["constraints"]:
        for tag in c["target_tag"].split("|"):
            index.setdefault(tag, []).append((c["target_field"], c["enum"]))
    return index


def render_reference(vocab: dict) -> str:
    """Render the per-tag reference markdown for ``vocab`` (the parsed catalog).
    Pure: takes the catalog dict, returns the document string — the same bytes
    the script writes to ``0.1-reference.md``. Importable so a contract test can
    assert the committed doc equals a fresh render."""
    emitters = build_emitter_index(vocab)
    enums = build_enum_index(vocab)
    version = vocab["vocabulary_version"]
    tags = vocab["tags"]

    lines = [
        f"# Vocabulary v{version} — per-tag reference",
        "",
        "Generated from `0.1.json` by `packages/python/tools/render_vocabulary_reference.py` — do not edit by hand; regenerate after changing the JSON.",
        "",
        f"{len(tags)} tags. Grouped by category; `incident` marks a tag that reports something going wrong, all others record routine events.",
        "",
    ]

    for category in vocab["categories"]:
        in_cat = [t for t in tags if t["category"] == category]
        if not in_cat:
            continue
        lines.append(f"## {category}")
        lines.append("")
        for tag in in_cat:
            name = tag["name"]
            marker = " (incident)" if tag["stratum"] == "incident" else ""
            lines.append(f"### `{name}`{marker}")
            lines.append("")
            payload = ", ".join(f"`{f}`" for f in tag["payload"]) or "none"
            lines.append(f"- Payload: {payload}")
            op, loc = emitters.get(name, ("?", "?"))
            lines.append(f"- Emitted by `{op}` ({loc})")
            for field, values in enums.get(name, []):
                allowed = ", ".join(f"`{v}`" for v in values)
                lines.append(f"- `{field}` must be one of: {allowed}")
            lines.append("")
            lines.append(tag["note"])
            lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if the committed reference is stale instead of writing",
    )
    args = p.parse_args(argv)

    vocab = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    rendered = render_reference(vocab)

    if args.check:
        current = REFERENCE_PATH.read_text(encoding="utf-8") if REFERENCE_PATH.exists() else ""
        if current != rendered:
            print(
                f"[reference] STALE: {REFERENCE_PATH.relative_to(REPO_ROOT)} does not match "
                f"{VOCAB_PATH.relative_to(REPO_ROOT)} — run tools/render_vocabulary_reference.py",
                file=sys.stderr,
            )
            return 1
        print("[reference] OK")
        return 0

    REFERENCE_PATH.write_text(rendered, encoding="utf-8")
    print(f"[reference] wrote {REFERENCE_PATH.relative_to(REPO_ROOT)} ({len(vocab['tags'])} tags)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

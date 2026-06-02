#!/usr/bin/env python3
"""Parity check: every emit() in the cascade_img package uses a tag that
exists in the locked vocabulary at ``signals/versions/0.1.json``.

Walks the package via AST. For each ``emit("TAG", ...)`` call, extracts the
literal first argument and asserts it appears in the vocabulary's tag list.
Exits non-zero with a structured drift report on mismatch.

Usage:
    python3 tools/check_vocabulary_parity.py
    python3 tools/check_vocabulary_parity.py --vocab src/cascade_img/vocabulary/versions/0.1.json

Run as part of the package's CI before every release. A drift is a defect
on equal footing with a failing test — the daemon's contract is what it
emits, and emitting a tag the vocabulary doesn't know is silent breakage.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path


def find_emit_calls(root: Path) -> list[tuple[Path, int, str]]:
    """Walk all .py files under root; return [(file, lineno, tag), ...] for every
    emit("TAG", ...) call with a literal string first argument.
    """
    calls: list[tuple[Path, int, str]] = []
    for py in root.rglob("*.py"):
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        except SyntaxError as e:
            print(f"[parity] skipping unparseable {py}: {e}", file=sys.stderr)
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            name = None
            if (isinstance(func, ast.Name) and func.id == "emit") or (
                isinstance(func, ast.Attribute) and func.attr == "emit"
            ):
                name = "emit"
            if name != "emit" or not node.args:
                continue
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                calls.append((py, node.lineno, first.value))
    return calls


def load_vocab(path: Path) -> set[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    return {t["name"] for t in data.get("tags", [])}


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--vocab",
        default="src/cascade_img/vocabulary/versions/0.1.json",
        help="path to the locked vocabulary JSON",
    )
    p.add_argument(
        "--src",
        default="src/cascade_img",
        help="root of the package to walk",
    )
    args = p.parse_args(argv)

    pkg_root = Path(__file__).parent.parent
    vocab_path = pkg_root / args.vocab
    src_path = pkg_root / args.src

    if not vocab_path.exists():
        print(f"[parity] vocabulary not found: {vocab_path}", file=sys.stderr)
        return 2
    if not src_path.exists():
        print(f"[parity] source root not found: {src_path}", file=sys.stderr)
        return 2

    vocab = load_vocab(vocab_path)
    calls = find_emit_calls(src_path)

    drift: list[tuple[Path, int, str]] = []
    for path, lineno, tag in calls:
        if tag not in vocab:
            drift.append((path, lineno, tag))

    print(f"[parity] vocabulary: {len(vocab)} tags at {vocab_path.relative_to(pkg_root)}")
    print(f"[parity] emit() calls: {len(calls)} in {src_path.relative_to(pkg_root)}")

    if drift:
        print(f"[parity] DRIFT: {len(drift)} emit() calls reference unknown tags:")
        for path, lineno, tag in drift:
            rel = path.relative_to(pkg_root)
            print(f"  {rel}:{lineno}  emit({tag!r})  -- not in vocabulary")
        return 1

    # Also report tags in vocabulary that no emit() call uses — not a failure,
    # but useful drift signal in the other direction.
    used = {tag for _, _, tag in calls}
    unused = vocab - used
    if unused:
        print(f"[parity] note: {len(unused)} vocabulary tags have no emit() callsite:")
        for tag in sorted(unused):
            print(f"  {tag}")

    print("[parity] OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Parity check: every emit() in the cascade_img package uses a tag that
exists in the locked vocabulary at ``vocabulary/versions/0.1.json``.

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
import hashlib
import json
import sys
from pathlib import Path


def compute_tag_set_hash(data: dict) -> str:
    """sha256 over the sorted ``"<name>:<comma-joined required payload>"`` lines —
    the tag surface consumers actually key on (tag names + required payload
    fields). Notes, sequence/timing rules, and ``optional_payload`` are
    deliberately excluded so prose edits and additive rule-field work never churn
    the hash; only a change to a tag's name or required payload does.
    """
    lines = sorted(f"{t['name']}:{','.join(t.get('payload', []))}" for t in data.get("tags", []))
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


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


def find_unmapped_tags(data: dict) -> list[str]:
    """Tag names not claimed by any operator's ``emits`` in the catalog.

    The ``operators`` map promises every tag traces to the component (and file)
    that emits it; an unmapped tag renders as ``Emitted by ? (?)`` in the
    generated ``0.1-reference.md``. The tag-list and emit-site checks can't catch
    this — the tag exists and is emitted — so this is its own guard (origin: the
    five video/loop tags shipped unmapped, 2026-06).
    """
    mapped: set[str] = set()
    for op in data.get("operators", {}).get("operators", []):
        mapped.update(op.get("emits", []))
    return sorted(t["name"] for t in data.get("tags", []) if t["name"] not in mapped)


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

    # Lock-integrity hash (additive to the existing checks). When the catalog is
    # locked, the stored tag_set_hash must match the current tag surface. This
    # forces every tag addition/change to acknowledge itself by updating the hash
    # in the SAME commit — catching silent catalog drift like the 47-vs-48
    # companion-doc desync (2026-06-10), which rode in with a tag addition.
    raw = json.loads(vocab_path.read_text(encoding="utf-8"))
    if raw.get("locked"):
        stored = raw.get("tag_set_hash")
        expected = compute_tag_set_hash(raw)
        if stored is not None and stored != expected:
            print(
                "[parity] TAG-SET HASH MISMATCH: the tag surface changed but "
                "tag_set_hash was not updated.",
                file=sys.stderr,
            )
            print(f"[parity]   stored   = {stored}", file=sys.stderr)
            print(f"[parity]   expected = {expected}", file=sys.stderr)
            print(
                "[parity]   catalog changed: if intentional, update tag_set_hash to the "
                "expected value in the same commit (both catalog copies) — see "
                "vocabulary/README.md 'How to extend'.",
                file=sys.stderr,
            )
            return 1

    # Operator-coverage: every tag must be claimed by some operator's `emits`,
    # else it renders as "Emitted by ? (?)" in the generated reference.
    unmapped = find_unmapped_tags(raw)
    if unmapped:
        print(
            f"[parity] OPERATOR COVERAGE GAP: {len(unmapped)} tag(s) are claimed by "
            "no operator's 'emits' in the catalog — they render as "
            "'Emitted by ? (?)' in 0.1-reference.md:",
            file=sys.stderr,
        )
        for tag in unmapped:
            print(f"  {tag}", file=sys.stderr)
        print(
            "[parity]   add each to the emitting operator's 'emits' list (both "
            "catalog copies), then regenerate the reference.",
            file=sys.stderr,
        )
        return 1

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

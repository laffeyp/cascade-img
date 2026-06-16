#!/usr/bin/env python3
"""Render the per-harness agent entry files from the orientation block in AGENTS.md.

Every AI coding harness auto-loads a *different* filename on startup — Claude Code
reads ``CLAUDE.md``, Gemini CLI ``GEMINI.md``, Copilot ``.github/copilot-instructions.md``,
Cursor ``.cursor/rules/*.mdc``, Windsurf ``.windsurfrules``, Cline ``.clinerules`` — while
``AGENTS.md`` is the cross-tool open standard that the rest read. So an agent that boots
in this repo is oriented only if *its* file exists. This script keeps all of them in
existence and in sync from one source: the ``AGENT-ORIENTATION`` block in ``AGENTS.md``.

``AGENTS.md`` stays the single hand-edited source of truth; the entry files are generated,
never hand-edited. A CI step runs ``--check`` and fails the build if any committed file is
stale — the same pattern as ``render_vocabulary_reference.py``.

Two kinds of output:
  * derived entry files — banner + (optional frontmatter) + the orientation block (doc
    links re-based for the file's location) + a pointer to the full AGENTS.md manual.
  * a verbatim mirror of AGENTS.md into ``packages/python/`` so the docs travel inside the
    source distribution (the sdist builds from ``packages/python/``, not the repo root).

Usage:
    python3 tools/render_agent_entrypoints.py            # regenerate
    python3 tools/render_agent_entrypoints.py --check    # CI: fail if any file is stale
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
PKG_DIR = REPO_ROOT / "packages" / "python"
AGENTS_PATH = REPO_ROOT / "AGENTS.md"

START_MARKER = "<!-- AGENT-ORIENTATION:START -->"
END_MARKER = "<!-- AGENT-ORIENTATION:END -->"

BANNER = (
    "<!-- Generated from the AGENT-ORIENTATION block in AGENTS.md by "
    "packages/python/tools/render_agent_entrypoints.py.\n"
    "     Do not edit by hand — edit that block in AGENTS.md and regenerate. -->"
)

POINTER = (
    "**Full operator guide:** [AGENTS.md]({agents}) — the complete tool reference, the "
    "prompt-part details, identity-lock guidance, and the failure-mode→action table."
)


@dataclass(frozen=True)
class Target:
    """One generated entry file.

    base / relpath — where it is written.
    link_prefix    — replaces ``./`` in the orientation block's doc links so they resolve
                     from this file's directory (the docs live at the repo root).
    agents_link    — the relative path to AGENTS.md used in the pointer line.
    frontmatter    — tool-specific header (Cursor wants YAML), or None.
    """

    base: Path
    relpath: str
    link_prefix: str
    agents_link: str
    frontmatter: str | None = None

    @property
    def path(self) -> Path:
        return self.base / self.relpath


_CURSOR_FRONTMATTER = (
    "---\n"
    "description: cascade-img — what it is and how an agent operates it\n"
    "alwaysApply: true\n"
    "---"
)

# Repo-root entry files (where each harness actually auto-loads them) + the
# packages/python mirror copies that ship in the sdist. The .github and .cursor
# files are working-checkout config, not source-dist navigation docs, so they are
# intentionally NOT mirrored into the package.
DERIVED_TARGETS: list[Target] = [
    # --- repo root: the files harnesses read on startup ---
    Target(REPO_ROOT, "CLAUDE.md", "./", "./AGENTS.md"),
    Target(REPO_ROOT, "GEMINI.md", "./", "./AGENTS.md"),
    Target(REPO_ROOT, ".windsurfrules", "./", "./AGENTS.md"),
    Target(REPO_ROOT, ".clinerules", "./", "./AGENTS.md"),
    Target(REPO_ROOT, ".github/copilot-instructions.md", "../", "../AGENTS.md"),
    Target(
        REPO_ROOT, ".cursor/rules/cascade-img.mdc", "../../", "../../AGENTS.md", _CURSOR_FRONTMATTER
    ),
    # --- packages/python mirror: rides along in the sdist (AGENTS.md sits beside them) ---
    Target(PKG_DIR, "CLAUDE.md", "../../", "./AGENTS.md"),
    Target(PKG_DIR, "GEMINI.md", "../../", "./AGENTS.md"),
    Target(PKG_DIR, ".windsurfrules", "../../", "./AGENTS.md"),
    Target(PKG_DIR, ".clinerules", "../../", "./AGENTS.md"),
]

# Verbatim copy: repo-root AGENTS.md -> packages/python/AGENTS.md, kept byte-identical
# (like the root vocabulary JSON is mirrored into the package data).
MIRROR_AGENTS_PATH = PKG_DIR / "AGENTS.md"


def extract_orientation(agents_text: str) -> str:
    """Return the text between the orientation markers, stripped. Fail loudly if absent."""
    try:
        start = agents_text.index(START_MARKER) + len(START_MARKER)
        end = agents_text.index(END_MARKER)
    except ValueError as e:
        raise SystemExit(
            f"[entrypoints] AGENTS.md is missing the {START_MARKER} / {END_MARKER} "
            f"markers — cannot render entry files."
        ) from e
    if end < start:
        raise SystemExit("[entrypoints] AGENTS.md orientation markers are out of order.")
    block = agents_text[start:end].strip()
    if not block:
        raise SystemExit("[entrypoints] AGENTS.md orientation block is empty.")
    return block


def render_entrypoint(orientation: str, target: Target) -> str:
    """Render one derived entry file's full bytes. Pure — a contract test asserts the
    committed file equals this for every target, so generation can't silently drift."""
    block = orientation.replace("](./", f"]({target.link_prefix}")
    parts: list[str] = []
    if target.frontmatter:
        parts.append(target.frontmatter)
        parts.append("")
    parts.append(BANNER)
    parts.append("")
    parts.append(block)
    parts.append("")
    parts.append(POINTER.format(agents=target.agents_link))
    parts.append("")
    return "\n".join(parts)


def planned_outputs() -> list[tuple[Path, str]]:
    """All (path, content) pairs this script is responsible for — derived files + the
    verbatim AGENTS.md mirror. The single source of truth for both --check and writing."""
    agents_text = AGENTS_PATH.read_text(encoding="utf-8")
    orientation = extract_orientation(agents_text)
    outputs = [(t.path, render_entrypoint(orientation, t)) for t in DERIVED_TARGETS]
    outputs.append((MIRROR_AGENTS_PATH, agents_text))
    return outputs


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--check",
        action="store_true",
        help="exit non-zero if any committed entry file is stale instead of writing",
    )
    args = p.parse_args(argv)

    outputs = planned_outputs()

    if args.check:
        stale = []
        for path, content in outputs:
            current = path.read_text(encoding="utf-8") if path.exists() else None
            if current != content:
                stale.append(path)
        if stale:
            print(
                "[entrypoints] STALE: the following do not match the AGENTS.md orientation "
                "block — run tools/render_agent_entrypoints.py:",
                file=sys.stderr,
            )
            for path in stale:
                print(f"  {path.relative_to(REPO_ROOT)}", file=sys.stderr)
            return 1
        print(f"[entrypoints] OK ({len(outputs)} files up to date)")
        return 0

    for path, content in outputs:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"[entrypoints] wrote {len(outputs)} files from AGENTS.md")
    return 0


if __name__ == "__main__":
    sys.exit(main())

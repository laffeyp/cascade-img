"""Mirror the repo-root operator docs into the package's ``guide/`` data dir.

The operator guide ships inside the wheel (so a pip-installed, repo-less agent
has the full manual available through the ``cascade_guide`` MCP tool), but the
source of truth is the repo-root docs. This script copies them into
``src/cascade_img/guide/``. Run it after editing any operator doc; CI/build runs
it with ``--check`` to fail on drift.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# tools/ -> packages/python/ -> packages/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_GUIDE_DIR = Path(__file__).resolve().parents[1] / "src" / "cascade_img" / "guide"

# (repo-root source path, bundled dest filename)
_DOCS: tuple[tuple[str, str], ...] = (
    ("AGENTS.md", "AGENTS.md"),
    ("RUNBOOK.md", "RUNBOOK.md"),
    ("CAPABILITIES.md", "CAPABILITIES.md"),
    ("ARCHITECTURE.md", "ARCHITECTURE.md"),
    ("AGENT_RUNDOWN.md", "AGENT_RUNDOWN.md"),
    ("examples/generate-a-single-image.md", "example-generate-a-single-image.md"),
    ("examples/generate-a-batch.md", "example-generate-a-batch.md"),
    ("examples/generate-a-video.md", "example-generate-a-video.md"),
)


def _pairs() -> list[tuple[Path, Path, str]]:
    return [(_REPO_ROOT / src_rel, _GUIDE_DIR / dest, src_rel) for src_rel, dest in _DOCS]


def check() -> int:
    drift: list[str] = []
    for src, dest, label in _pairs():
        if not src.exists():
            print(f"missing source: {src}", file=sys.stderr)
            drift.append(label)
            continue
        if not dest.exists() or dest.read_text(encoding="utf-8") != src.read_text(encoding="utf-8"):
            drift.append(label)
    if drift:
        print(
            "guide docs out of sync with repo root: "
            + ", ".join(drift)
            + "\nrun: python tools/sync_guide_docs.py",
            file=sys.stderr,
        )
        return 1
    print(f"guide docs in sync ({len(_DOCS)} files)")
    return 0


def sync() -> int:
    _GUIDE_DIR.mkdir(parents=True, exist_ok=True)
    for src, dest, label in _pairs():
        if not src.exists():
            print(f"missing source: {src}", file=sys.stderr)
            return 1
        dest.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"synced {label} -> guide/{dest.name}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="sync_guide_docs")
    parser.add_argument("--check", action="store_true", help="exit non-zero on drift; do not write")
    args = parser.parse_args()
    return check() if args.check else sync()


if __name__ == "__main__":
    raise SystemExit(main())

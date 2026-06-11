"""Contract: the generated agent entry files match the AGENTS.md orientation block.

Mirrors the vocabulary-reference contract. Every committed entry file — the repo-root
ones each harness auto-loads (CLAUDE.md, GEMINI.md, the Cursor/Windsurf/Cline/Copilot
files) plus the packages/python sdist mirror — must equal a fresh render. If AGENTS.md's
orientation block changed without regenerating, this fails: the same guarantee the CI
``render_agent_entrypoints.py --check`` step enforces, but as a unit-tier test so it also
trips locally under a bare ``pytest``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# tools/ isn't an importable package; load the renderer by path (as test_image_checks does).
# Register in sys.modules before exec so @dataclass can resolve the module on 3.14.
_TOOLS = Path(__file__).resolve().parents[2] / "tools" / "render_agent_entrypoints.py"
_spec = importlib.util.spec_from_file_location("render_agent_entrypoints", _TOOLS)
assert _spec and _spec.loader
render = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = render
_spec.loader.exec_module(render)

_OUTPUTS = render.planned_outputs()
_IDS = [str(path.relative_to(render.REPO_ROOT)) for path, _ in _OUTPUTS]


@pytest.mark.contract
def test_agents_md_has_orientation_block():
    text = render.AGENTS_PATH.read_text(encoding="utf-8")
    assert render.START_MARKER in text
    assert render.END_MARKER in text
    block = render.extract_orientation(text)
    # load-bearing content, not just a stray heading
    assert "primary operator" in block
    assert "cascade-mcp" in block


@pytest.mark.contract
def test_renders_every_harness_file():
    # guard against a target being silently dropped from the matrix
    rel = set(_IDS)
    assert "CLAUDE.md" in rel
    assert "GEMINI.md" in rel
    assert ".github/copilot-instructions.md" in rel
    assert ".cursor/rules/cascade-img.mdc" in rel
    assert ".windsurfrules" in rel
    assert ".clinerules" in rel
    assert "packages/python/AGENTS.md" in rel  # the sdist mirror


@pytest.mark.contract
@pytest.mark.parametrize("path, expected", _OUTPUTS, ids=_IDS)
def test_entry_file_up_to_date(path: Path, expected: str):
    assert path.exists(), f"{path} missing — run tools/render_agent_entrypoints.py"
    assert path.read_text(encoding="utf-8") == expected, (
        f"{path.relative_to(render.REPO_ROOT)} is stale — run tools/render_agent_entrypoints.py"
    )

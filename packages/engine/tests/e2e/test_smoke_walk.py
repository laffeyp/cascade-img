"""Live end-to-end walk, folded into the suite as a gated e2e test.

This drives the real MCP stdio transport against a live bridge + real
Midjourney — the observation contract for the whole loop (compose -> imagine
-> wait -> crop -> promote -> log). It costs MJ credits and automates a Discord
user account, so it is skipped unless the operator opts in:

    CASCADE_LIVE=1 CASCADE_ENV_FILE=/path/to/.env pytest -m e2e

The default `pytest` run collects it and skips it (no credentials needed), so
CI and contributors stay green without a live account. ``tools/smoke_mcp_walk.py``
remains the hand-run entry point; this test invokes the same script so the two
never drift.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.e2e

_LIVE = os.environ.get("CASCADE_LIVE") == "1"
_ENV_FILE = os.environ.get("CASCADE_ENV_FILE")


@pytest.mark.skipif(
    not (_LIVE and _ENV_FILE),
    reason="live e2e walk — set CASCADE_LIVE=1 and CASCADE_ENV_FILE=/path/to/.env to run",
)
def test_smoke_walk_grid_only():
    """Boot the bridge, walk every MCP tool against real MJ, assert exit 0.

    Invokes tools/smoke_mcp_walk.py as a subprocess (the way an operator runs
    it) so this test and the script share one code path. Grid-only (no upscale)
    keeps it to ~30s of live time.
    """
    engine_root = Path(__file__).resolve().parents[2]  # packages/engine
    script = engine_root / "tools" / "smoke_mcp_walk.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            _ENV_FILE,
            "--wait-timeout",
            "180",
            "--bridge-boot-timeout",
            "60",
        ],
        cwd=engine_root,
        timeout=420,
        check=False,
    )
    assert proc.returncode == 0, f"smoke walk exited {proc.returncode} (expected 0)"

"""Live end-to-end walk, folded into the suite as a gated e2e test.

This drives the real MCP stdio transport against a live bridge + real
Midjourney — the observation check for the whole loop (compose -> imagine
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

requires_live = pytest.mark.skipif(
    not (_LIVE and _ENV_FILE),
    reason="live e2e walk — set CASCADE_LIVE=1 and CASCADE_ENV_FILE=/path/to/.env to run",
)


def _run_smoke_walk(extra_args: list[str], *, wait_timeout: int, proc_timeout: int) -> None:
    """Run tools/smoke_mcp_walk.py as a subprocess (the way an operator runs it)
    so each e2e test and the script share one code path. Asserts a clean exit 0.

    ``extra_args`` selects the variant (e.g. ``["--upscale", "all"]``);
    ``wait_timeout`` is the per-job MJ wait budget, ``proc_timeout`` the outer
    subprocess kill budget (bridge boot + wait + curation headroom).
    """
    engine_root = Path(__file__).resolve().parents[2]  # packages/python
    script = engine_root / "tools" / "smoke_mcp_walk.py"
    proc = subprocess.run(
        [
            sys.executable,
            str(script),
            "--env-file",
            _ENV_FILE,
            "--wait-timeout",
            str(wait_timeout),
            "--bridge-boot-timeout",
            "60",
            *extra_args,
        ],
        cwd=engine_root,
        timeout=proc_timeout,
        check=False,
    )
    assert proc.returncode == 0, (
        f"smoke walk {extra_args or '(grid-only)'} exited {proc.returncode} (expected 0)"
    )


@requires_live
def test_smoke_walk_grid_only():
    """Walk every MCP tool against real MJ with no upscale — the fast variant
    (~30s live): compose -> imagine -> wait -> crop -> promote -> log."""
    _run_smoke_walk([], wait_timeout=180, proc_timeout=420)


@requires_live
def test_smoke_walk_upscale_all():
    """The upscale path: ``--upscale all`` fires U1-U4 and waits for four real
    upscaled images, so it runs longer than the grid-only variant."""
    _run_smoke_walk(["--upscale", "all"], wait_timeout=300, proc_timeout=540)


@requires_live
def test_smoke_walk_alpha_key():
    """The curation path with background removal: ``--alpha-key`` exercises the
    flood-fill keyer on the cropped quadrant before promote."""
    _run_smoke_walk(["--alpha-key"], wait_timeout=180, proc_timeout=420)

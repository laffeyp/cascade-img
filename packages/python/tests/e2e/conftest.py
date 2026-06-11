"""Live e2e fixtures: one bridge + one base render, shared across capability
tests so the whole matrix costs the fewest possible Midjourney renders.

Gated: every fixture skips unless ``CASCADE_LIVE=1`` and ``CASCADE_ENV_FILE`` are
set. The bridge runs on a dedicated port (5099) so it never collides with the
smoke-walk tests' own bridge on 5000.
"""

from __future__ import annotations

import contextlib
import importlib.util
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

import pytest

_LIVE = os.environ.get("CASCADE_LIVE") == "1"
_ENV_FILE = os.environ.get("CASCADE_ENV_FILE")
_PORT = int(os.environ.get("CASCADE_E2E_PORT", "5099"))

# tools/ isn't an importable package; load the image-property checks by path.
_CHECKS_PATH = Path(__file__).resolve().parents[2] / "tools" / "image_checks.py"
_spec = importlib.util.spec_from_file_location("image_checks", _CHECKS_PATH)
assert _spec and _spec.loader
image_checks = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(image_checks)


@pytest.fixture(scope="session")
def event_log_path(tmp_path_factory) -> Path:
    """Per-run JSONL path the spawned bridge's ``CASCADE_EVENT_LOG`` sink (sprint
    012) appends every vocabulary signal to. The trace-gate test reads it back and
    runs ``check_trace`` over the live run's grammar (sprint 015)."""
    return tmp_path_factory.mktemp("e2e-events") / "events.jsonl"


@pytest.fixture(scope="session")
def live_backend(tmp_path_factory, event_log_path):
    """Spawn a real bridge (its own port, isolated output dir), wait for Discord
    to connect, yield a backend pointed at it, then tear the bridge down."""
    if not (_LIVE and _ENV_FILE):
        pytest.skip("live capability e2e — set CASCADE_LIVE=1 and CASCADE_ENV_FILE")

    from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend

    out_dir = tmp_path_factory.mktemp("e2e-bridge-out")
    log_path = out_dir / "bridge.log"
    env = {
        **os.environ,
        "CASCADE_DOTENV": _ENV_FILE,
        "PORT": str(_PORT),
        "MJ_OUTPUT_DIR": str(out_dir),
        # Durable signal trace for the trace-gate test (sprint 015). The sink
        # reads this env per-emit inside the bridge process and appends one JSONL
        # line per signal; best-effort, so it can never break the live path.
        "CASCADE_EVENT_LOG": str(event_log_path),
    }
    fh = log_path.open("w", encoding="utf-8")
    proc = subprocess.Popen(
        [sys.executable, "-u", "-m", "cascade_img.backends.midjourney_discord.bridge"],
        stdout=fh,
        stderr=subprocess.STDOUT,
        env=env,
        start_new_session=True,
    )
    backend = MidjourneyDiscordBackend(f"http://127.0.0.1:{_PORT}")

    try:
        deadline = time.time() + 90
        ready = False
        while time.time() < deadline:
            if proc.poll() is not None:
                pytest.fail(f"bridge exited early (rc={proc.returncode}); see {log_path}")
            try:
                if backend.health().get("discord_ready"):
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(1)
        if not ready:
            pytest.fail(f"bridge never became discord_ready within 90s; see {log_path}")
        yield backend
    finally:
        if proc.poll() is None:
            with contextlib.suppress(ProcessLookupError):
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            with contextlib.suppress(subprocess.TimeoutExpired, ProcessLookupError):
                proc.wait(timeout=10)
            if proc.poll() is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        fh.close()


@pytest.fixture(scope="session")
def base_job(live_backend) -> dict:
    """One real ``upscale="all"`` render, reused by every action and curation
    test. Subject is a plain icon on a solid white background so the alpha-key
    curation check has a uniform background to cut."""
    from cascade_img.prompt.composer import PromptComposer, Subject

    prompt = PromptComposer().compose(
        Subject(
            text="a simple flat vector icon of a single solid red circle",
            constraints=["centered", "solid plain white background", "no shadow", "no gradient"],
        ),
        aspect_ratio="1:1",
    )
    res = live_backend.imagine(prompt, asset_id="captest_base", upscale="all")
    rec = live_backend.wait(res["job_id"], timeout=600)
    assert rec.get("status") == "done", f"base render did not finish: {rec}"
    rec["job_id"] = res["job_id"]
    return rec


@pytest.fixture(scope="session")
def checks():
    """The image-property check module (is_animated / has_transparency / …)."""
    return image_checks

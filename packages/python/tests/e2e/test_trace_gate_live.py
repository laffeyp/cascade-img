"""Live trace-gate e2e (sprint 015).

Every live run now validates the declared sequence and timing grammar end to end,
not just file existence. The spawned bridge writes a durable JSONL signal log
(``CASCADE_EVENT_LOG``, wired in ``conftest.py``); these tests read it back and run
the trace checker (sprint 014) over the real run.

Gated like the rest of the e2e suite: skipped unless ``CASCADE_LIVE=1`` and
``CASCADE_ENV_FILE`` are set. They tolerate an open session — read while the bridge
is still up, so ``BRIDGE_SHUTDOWN`` need not have landed; ``check_trace`` does not
require it. They depend on ``base_job`` so a full compose -> imagine(all) -> wait ->
done render has populated the trace before it is graded.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from cascade_img.vocabulary.trace_check import check_trace, load_catalog

pytestmark = pytest.mark.e2e


def _read_events(event_log_path: Path) -> list[dict]:
    assert event_log_path.exists(), (
        f"bridge wrote no event log at {event_log_path} — CASCADE_EVENT_LOG not honored"
    )
    events = [
        json.loads(line)
        for line in event_log_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert events, "event log is empty — no signals captured from the live run"
    return events


def test_live_trace_has_no_error_violations(base_job, event_log_path):
    """The full live render leaves a trace that satisfies every sequence rule.
    Window timing overruns are warnings (a slow MJ day is allowed); only
    error-severity violations fail the gate."""
    violations = check_trace(_read_events(event_log_path), load_catalog())
    errors = [v for v in violations if v.severity == "error"]
    assert not errors, "live trace-gate errors:\n" + "\n".join(
        f"  {v.rule} [{v.slice_key}] {v.message}" for v in errors
    )


def test_live_trace_contains_full_lifecycle_for_base_job(base_job, event_log_path):
    """Observation check: the JSONL carries the full lifecycle sequence for the
    base render's job_id, in order."""
    job_id = base_job["job_id"]
    seq = [
        e["tag"]
        for e in _read_events(event_log_path)
        if (e.get("payload") or {}).get("job_id") == job_id
    ]
    for tag in ("IMAGINE_FIRED", "GRID_MATCHED", "GRID_RECEIVED", "JOB_COMPLETED"):
        assert tag in seq, f"{tag} missing from live trace for job {job_id}: {seq}"
    assert seq.index("IMAGINE_FIRED") < seq.index("GRID_MATCHED") < seq.index("JOB_COMPLETED")


def test_live_session_framing_present(base_job, event_log_path):
    """The bridge session opens with CASCADE_INIT + CONFIG_VALIDATED, and Discord
    connects before any IMAGINE_FIRED — the session-open grammar, observed live."""
    tags = [e["tag"] for e in _read_events(event_log_path)]
    assert "CASCADE_INIT" in tags and "CONFIG_VALIDATED" in tags
    assert "DISCORD_CONNECTED" in tags
    assert tags.index("DISCORD_CONNECTED") < tags.index("IMAGINE_FIRED")


def test_cascade_trace_check_cli_passes_on_live_log(base_job, event_log_path):
    """The shipped console script validates the live log too: running the checker
    as a process over the real JSONL exits 0 (no error-severity violations)."""
    proc = subprocess.run(
        [sys.executable, "-m", "cascade_img.vocabulary.trace_check", str(event_log_path)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"cascade-trace-check exited {proc.returncode} on the live log:\n"
        f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
    )

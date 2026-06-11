"""Contract for the offline trace checker (sprint 014).

Every test runs against the REAL post-013 catalog (``load_catalog()``), so these
hand-built traces double as the executable specification of what a grammatical
run looks like — and of each way one can break. The window invariants are
warnings by design (a slow MJ day must not fail a gate); everything else is an
error. The wrong-slice test is load-bearing: job A's terminal must never poison
job B.
"""

from __future__ import annotations

from cascade_img.vocabulary.trace_check import Violation, check_trace, load_catalog

VOCAB = load_catalog()


def ev(tag: str, ts: float = 0.0, **payload) -> dict:
    return {"tag": tag, "ts": ts, "payload": payload}


def _legal_job_trace() -> list[dict]:
    """A fully legal end-to-end upscale='all' job."""
    return [
        ev("CONFIG_VALIDATED", ts=0),
        ev("CASCADE_INIT", ts=1, package_version="0.1.0", backend="midjourney_discord"),
        ev("DISCORD_CONNECTED", ts=2, user_id=1),
        ev("IMAGINE_FIRED", ts=10, job_id="j1", upscale="all"),
        ev("GRID_MATCHED", ts=20, job_id="j1"),
        ev("GRID_RECEIVED", ts=25, job_id="j1"),
        ev("UPSCALE_REQUESTED", ts=30, job_id="j1", slot=1),
        ev("UPSCALE_RECEIVED", ts=40, job_id="j1", slot=1),
        ev("JOB_COMPLETED", ts=300, job_id="j1"),  # within the 600s 'all' band
    ]


def test_legal_trace_zero_violations():
    assert check_trace(_legal_job_trace(), VOCAB) == []


def test_out_of_order_grid_received_before_matched_is_error():
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="j1", upscale=None),
        ev("GRID_RECEIVED", ts=2, job_id="j1"),  # before its GRID_MATCHED
        ev("GRID_MATCHED", ts=3, job_id="j1"),
        ev("JOB_COMPLETED", ts=4, job_id="j1"),
    ]
    vs = check_trace(trace, VOCAB)
    assert any(
        v.rule == "pairing_ordering" and v.severity == "error" and v.event["tag"] == "GRID_RECEIVED"
        for v in vs
    )


def test_post_terminal_lifecycle_tag_is_error():
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="j1", upscale=None),
        ev("GRID_MATCHED", ts=2, job_id="j1"),
        ev("GRID_RECEIVED", ts=3, job_id="j1"),
        ev("JOB_COMPLETED", ts=4, job_id="j1"),
        ev("GRID_MATCHED", ts=5, job_id="j1"),  # lifecycle tag after terminal, same job
    ]
    vs = check_trace(trace, VOCAB)
    assert any(
        v.rule == "terminal" and v.severity == "error" and v.event["tag"] == "GRID_MATCHED"
        for v in vs
    )


def test_post_terminal_exempt_tag_is_not_a_violation():
    """The derived/action/eviction/collision tags legitimately carry a completed
    job's id — they must pass (the 013 grammar correction in executable form)."""
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="j1", upscale="1"),
        ev("GRID_MATCHED", ts=2, job_id="j1"),
        ev("GRID_RECEIVED", ts=3, job_id="j1"),
        ev("UPSCALE_REQUESTED", ts=4, job_id="j1", slot=1),
        ev("UPSCALE_RECEIVED", ts=5, job_id="j1", slot=1),
        ev("JOB_COMPLETED", ts=6, job_id="j1"),
        ev("MJ_ACTION_REQUESTED", ts=7, job_id="j1"),  # press on the completed job
        ev("MJ_DERIVED_RECEIVED", ts=8, job_id="j1"),  # its derived result
        ev("JOB_EVICTED", ts=9, job_id="j1"),  # later evicted
    ]
    assert check_trace(trace, VOCAB) == []


def test_unresolved_mcp_tool_called_is_error():
    trace = [ev("MCP_TOOL_CALLED", ts=0, tool="imagine")]  # never resolves
    vs = check_trace(trace, VOCAB)
    assert any(v.rule == "pairing" and v.severity == "error" for v in vs)


def test_resolved_mcp_tool_call_is_clean():
    trace = [
        ev("MCP_TOOL_CALLED", ts=0, tool="status"),
        ev("MCP_TOOL_COMPLETED", ts=1, tool="status"),
    ]
    assert [v for v in check_trace(trace, VOCAB) if v.rule == "pairing"] == []


def test_window_overrun_is_a_warning_not_an_error():
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="j1", upscale=None),  # 'none' band: 180s
        ev("GRID_MATCHED", ts=2, job_id="j1"),
        ev("GRID_RECEIVED", ts=3, job_id="j1"),
        ev("JOB_COMPLETED", ts=300, job_id="j1"),  # 299s > 180s
    ]
    vs = check_trace(trace, VOCAB)
    window_vs = [v for v in vs if v.rule == "window"]
    assert len(window_vs) == 1
    assert window_vs[0].severity == "warning"
    # The overrun must NOT raise any error-severity violation.
    assert [v for v in vs if v.severity == "error"] == []


def test_wrong_slice_terminal_does_not_poison_other_job():
    """Job A's terminal must not flag job B's still-legitimate lifecycle tags."""
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="A", upscale=None),
        ev("IMAGINE_FIRED", ts=2, job_id="B", upscale=None),
        ev("GRID_MATCHED", ts=3, job_id="A"),
        ev("GRID_RECEIVED", ts=4, job_id="A"),
        ev("JOB_COMPLETED", ts=5, job_id="A"),
        ev("GRID_MATCHED", ts=6, job_id="B"),  # B progressing AFTER A's terminal
        ev("GRID_RECEIVED", ts=7, job_id="B"),
        ev("JOB_COMPLETED", ts=8, job_id="B"),
    ]
    assert check_trace(trace, VOCAB) == []


def test_cascade_init_without_prior_config_validated_is_error():
    """The corrected startup precondition (the live-gate finding of 2026-06-10):
    the daemon never announces CASCADE_INIT without a prior CONFIG_VALIDATED. The
    catalog originally declared this backwards as a forced_next; the live trace
    showed CONFIG_VALIDATED fires first (Config.from_env emits it, then main emits
    CASCADE_INIT)."""
    trace = [
        ev("CASCADE_INIT", ts=0, package_version="0.1.0", backend="midjourney_discord"),
        ev("CONFIG_VALIDATED", ts=1),  # too late — comes AFTER init
    ]
    vs = check_trace(trace, VOCAB)
    assert any(
        v.rule == "pairing_ordering" and v.severity == "error" and v.event["tag"] == "CASCADE_INIT"
        for v in vs
    )


def test_config_validated_without_cascade_init_is_clean():
    """--check-env / --doctor emit CONFIG_VALIDATED with no CASCADE_INIT; the
    pairing_ordering precondition does not require the from-tag to be followed, so
    a validate-only run is not a violation."""
    trace = [ev("CONFIG_VALIDATED", ts=0), ev("BRIDGE_CHECKENV_RAN", ts=1)]
    assert [v for v in check_trace(trace, VOCAB) if v.rule == "pairing_ordering"] == []


# The catalog no longer uses the forced_next kind after the 2026-06-10 startup-order
# correction, but the checker still supports it for future rules — exercise it with a
# synthetic vocab so the forced_next + or_exit_via logic stays covered.
_FORCED_NEXT_VOCAB = {
    "state_transitions": {
        "rules": [
            {
                "kind": "forced_next",
                "from_tag": "A_OPENED",
                "to_tags_allowed": ["A_DONE"],
                "or_exit_via": ["A_ABORTED"],
            }
        ]
    },
    "temporal_invariants": {"invariants": []},
}


def test_forced_next_satisfied_via_or_exit_via():
    trace = [ev("A_OPENED", ts=0), ev("A_ABORTED", ts=1)]
    assert [v for v in check_trace(trace, _FORCED_NEXT_VOCAB) if v.rule == "forced_next"] == []


def test_forced_next_unsatisfied_is_error():
    trace = [ev("A_OPENED", ts=0), ev("UNRELATED", ts=1)]
    vs = check_trace(trace, _FORCED_NEXT_VOCAB)
    assert any(v.rule == "forced_next" and v.severity == "error" for v in vs)


def test_violation_carries_slice_key_and_both_events():
    trace = [
        ev("DISCORD_CONNECTED", ts=0, user_id=1),
        ev("IMAGINE_FIRED", ts=1, job_id="j9", upscale=None),
        ev("GRID_MATCHED", ts=2, job_id="j9"),
        ev("GRID_RECEIVED", ts=3, job_id="j9"),
        ev("JOB_COMPLETED", ts=4, job_id="j9"),
        ev("UPSCALE_REQUESTED", ts=5, job_id="j9", slot=1),  # forbidden after terminal
    ]
    term = next(v for v in check_trace(trace, VOCAB) if v.rule == "terminal")
    assert isinstance(term, Violation)
    assert term.slice_key == "j9"
    assert term.event["tag"] == "UPSCALE_REQUESTED"
    assert term.prior["tag"] == "JOB_COMPLETED"

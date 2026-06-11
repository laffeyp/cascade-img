"""Behavior contract for PromptLog.

Verifies append → read roundtrip (the agent's working-memory use case), the
last-n slicing, the markdown render, and the signal payload on append.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cascade_img.prompt.prompt_log import AgentDecision, PromptLog
from cascade_img.vocabulary import clear, snapshot


def test_append_then_read_roundtrip(tmp_path: Path):
    clear()
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="mountain-icon",
        prompt="a mountain icon --ar 1:1 --v 7",
        backend="midjourney_discord",
        job_id="abc123",
        upscale="1",
        outputs={
            "image_path": "/tmp/mountain-icon.png",
            "grid_path": "/tmp/mountain-icon_grid.webp",
        },
    )
    log.append(
        asset_id="hero-portrait",
        prompt="a hero portrait --ar 1:1 --v 7",
        backend="midjourney_discord",
        job_id="def456",
    )
    records = log.read()
    assert len(records) == 2
    assert records[0]["asset_id"] == "mountain-icon"
    assert records[0]["job_id"] == "abc123"
    assert records[1]["asset_id"] == "hero-portrait"
    # signal contract
    tags = [r["tag"] for r in snapshot()]
    assert tags == ["PROMPT_LOGGED", "PROMPT_LOGGED"]
    assert snapshot()[0]["payload"]["asset_id"] == "mountain-icon"
    assert snapshot()[0]["payload"]["has_job_id"] is True


def test_read_last_n(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    for i in range(5):
        log.append(asset_id=f"a{i}", prompt=f"p{i}", backend="x")
    last_two = log.read(n=2)
    assert [r["asset_id"] for r in last_two] == ["a3", "a4"]


def test_read_empty_log(tmp_path: Path):
    log = PromptLog(tmp_path / "nonexistent.jsonl")
    assert log.read() == []


def test_agent_decision_enum_values_pass(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    for value in ("promote", "reroll", "escalate", "dry_run"):
        log.append(asset_id="x", prompt="p", backend="b", agent_decision=value)


def test_agent_decision_enum_object_pass(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(asset_id="x", prompt="p", backend="b", agent_decision=AgentDecision.PROMOTE)
    records = log.read()
    assert records[0]["agent_decision"] == "promote"


def test_agent_decision_invalid_raises(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    with pytest.raises(ValueError, match=r"agent_decision must be one of"):
        log.append(asset_id="x", prompt="p", backend="b", agent_decision="yeet")


def test_read_handles_concurrent_deletion(tmp_path: Path):
    """If the log file is deleted between PromptLog.read()'s internal check
    and its read, the method returns [] rather than raising FileNotFoundError.
    Simulated here by deleting before the call (the TOCTOU window is wider
    in the race, but the EAFP fix handles both shapes)."""
    log_path = tmp_path / "log.jsonl"
    log = PromptLog(log_path)
    log.append(asset_id="x", prompt="x", backend="midjourney_discord")
    assert log.path.exists()
    log_path.unlink()
    assert log.read() == []


def test_concurrent_appends_are_all_recorded(tmp_path: Path):
    """PromptLog advertises thread-safety; exercise the lock under 8 threads.
    All 200 appends must land as valid JSONL with none lost or torn."""
    import threading

    log = PromptLog(tmp_path / "log.jsonl")

    def worker(n: int) -> None:
        for i in range(25):
            log.append(asset_id=f"t{n}_{i}", prompt="p", backend="midjourney_discord")

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    records = log.read()
    assert len(records) == 8 * 25  # none dropped
    assert all(r.get("asset_id") for r in records)  # no torn/interleaved lines
    assert len({r["asset_id"] for r in records}) == 8 * 25  # all distinct, none clobbered


def test_read_skips_torn_line_keeps_the_rest(tmp_path: Path):
    """One torn or hand-edited JSONL line must not abort the whole read — the
    prompt log IS the agent's working memory across loop iterations, and losing
    every record to a single corrupt line is the larger failure. The bad line is
    skipped (and logged), the surviving records returned. (review #5)"""
    log_path = tmp_path / "log.jsonl"
    log = PromptLog(log_path)
    log.append(asset_id="a", prompt="p", backend="b")
    log.append(asset_id="b", prompt="p", backend="b")
    good = log_path.read_text().splitlines()
    # Insert a torn (truncated-JSON) line between the two good records.
    log_path.write_text(good[0] + "\n" + '{"asset_id": "torn", "prompt"' + "\n" + good[1] + "\n")

    records = log.read()
    assert [r["asset_id"] for r in records] == ["a", "b"]  # torn line skipped, rest survive


def test_read_skips_torn_line_under_last_n(tmp_path: Path):
    """The skip-and-continue holds under the last-n slice too: n counts surviving
    records, not raw lines. (review #5)"""
    log_path = tmp_path / "log.jsonl"
    log = PromptLog(log_path)
    for i in range(3):
        log.append(asset_id=f"a{i}", prompt="p", backend="b")
    lines = log_path.read_text().splitlines()
    log_path.write_text("\n".join([lines[0], "not json at all", lines[1], lines[2]]) + "\n")

    last_two = log.read(n=2)
    assert [r["asset_id"] for r in last_two] == ["a1", "a2"]


def test_render_markdown_contains_prompts(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="mountain-icon",
        prompt="a mountain icon",
        backend="midjourney_discord",
        job_id="abc",
        outputs={"image_path": "/tmp/mountain-icon.png"},
    )
    md = log.render_markdown()
    assert "mountain-icon" in md
    assert "a mountain icon" in md
    assert "abc" in md
    assert "/tmp/mountain-icon.png" in md


def test_append_with_error_marks_signal(tmp_path: Path):
    clear()
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="x",
        prompt="...",
        backend="midjourney_discord",
        error="discord 400: outdated",
    )
    rec = snapshot()[-1]
    assert rec["payload"]["has_error"] is True
    assert rec["payload"]["has_job_id"] is False


def test_render_markdown_tolerates_schema_incomplete_record(tmp_path: Path):
    """render_markdown degrades to placeholders on a valid-JSON but
    schema-incomplete record (a hand-edited or older-schema line that read()
    deliberately tolerates) instead of aborting the whole render with KeyError.
    (review bug-hunt)"""
    import json as _json

    log_path = tmp_path / "log.jsonl"
    log = PromptLog(log_path)
    log.append(asset_id="good", prompt="a real prompt", backend="midjourney_discord", job_id="j1")
    # A valid-JSON line missing prompt/ts/backend (e.g. hand-edited).
    with log_path.open("a", encoding="utf-8") as f:
        f.write(_json.dumps({"asset_id": "partial", "job_id": "j2"}) + "\n")

    md = log.render_markdown()  # must not raise
    assert "a real prompt" in md  # the good record renders
    assert "partial" in md  # the incomplete record renders, degraded
    assert "unknown" in md  # missing backend -> placeholder under the job line


def test_append_with_agent_decision(tmp_path: Path):
    """Agent decision is one of '', 'promote', 'reroll', 'escalate'."""
    clear()
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="mountain-icon",
        prompt="...",
        backend="midjourney_discord",
        job_id="abc",
        agent_decision="promote",
        agent_reason="quadrant U2 matches identity lock and aesthetic",
    )
    rec = snapshot()[-1]
    assert rec["payload"]["agent_decision"] == "promote"
    records = log.read()
    assert records[0]["agent_decision"] == "promote"
    assert "matches identity lock" in records[0]["agent_reason"]


def test_read_n_zero_returns_no_records(tmp_path: Path):
    """read(n=0) means 'last zero records' — [], not the [-0:] whole-list slice."""
    plog = PromptLog(tmp_path / "log.jsonl")
    plog.append(asset_id="a", prompt="p", backend="b")
    assert plog.read(n=0) == []
    assert len(plog.read(n=1)) == 1

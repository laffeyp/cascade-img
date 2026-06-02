"""Behavior contract for PromptLog.

Verifies append → read roundtrip (the agent's working-memory use case), the
last-n slicing, the markdown render, and the signal payload on append.
"""

from __future__ import annotations

from pathlib import Path

from cascade_img.instrumentation.runtime import clear, snapshot
from cascade_img.log import PromptLog


def test_append_then_read_roundtrip(tmp_path: Path):
    clear()
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="bird",
        prompt="pixel-art finch --ar 1:1 --v 7",
        backend="midjourney_discord",
        job_id="abc123",
        upscale="1",
        outputs={"image_path": "/tmp/bird.png", "grid_path": "/tmp/bird_grid.webp"},
    )
    log.append(
        asset_id="clue_a",
        prompt="a wet feather --ar 1:1 --v 7",
        backend="midjourney_discord",
        job_id="def456",
    )
    records = log.read()
    assert len(records) == 2
    assert records[0]["asset_id"] == "bird"
    assert records[0]["job_id"] == "abc123"
    assert records[1]["asset_id"] == "clue_a"
    # signal contract
    tags = [r["tag"] for r in snapshot()]
    assert tags == ["PROMPT_LOGGED", "PROMPT_LOGGED"]
    assert snapshot()[0]["payload"]["asset_id"] == "bird"
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


def test_render_markdown_contains_prompts(tmp_path: Path):
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="bird",
        prompt="pixel-art finch",
        backend="midjourney_discord",
        job_id="abc",
        outputs={"image_path": "/tmp/bird.png"},
    )
    md = log.render_markdown()
    assert "bird" in md
    assert "pixel-art finch" in md
    assert "abc" in md
    assert "/tmp/bird.png" in md


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


def test_append_with_agent_decision(tmp_path: Path):
    """Agent decision is one of '', 'promote', 'reroll', 'escalate'."""
    clear()
    log = PromptLog(tmp_path / "log.jsonl")
    log.append(
        asset_id="bird",
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

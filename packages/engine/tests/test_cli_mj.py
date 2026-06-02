"""Behavior contract for ``cascade-mj`` unified roll-and-log CLI.

Covers: registry loading, asset lookup, dry-run (full path without firing),
unknown asset_id structured error, malformed registry structured error.

Live-fire against a running bridge is not testable in the discipline ladder
— that's the smoke against your real .env. The dry-run path exercises
compose + log without external state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cascade_img.cli.mj import run
from cascade_img.cli.registry import AssetEntry, load_registry
from cascade_img.instrumentation.sdd import clear, snapshot


REGISTRY_BIRD = {
    "bird": {
        "subject": "pixel-art sprite of a small finch, side view",
        "constraints": ["transparent background"],
        "moodboard": "m7458053701014388751",
        "sref": "https://cdn.midjourney.com/x/0_0.png",
        "aspect_ratio": "1:1",
    },
    "clue_a": {
        "subject": "a single wet feather",
        "moodboard": "m7458053701014388751",
        "sref": "https://cdn.midjourney.com/x/0_0.png",
        "aspect_ratio": "1:1",
        "oref": "https://cdn/oref.png",
        "ow": 400,
    },
}


def _write_registry(tmp_path: Path, body) -> Path:
    p = tmp_path / "assets.json"
    p.write_text(json.dumps(body), encoding="utf-8")
    return p


def _tags():
    return [r["tag"] for r in snapshot()]


# --------------------- registry ---------------------


def test_registry_loads_two_assets(tmp_path):
    p = _write_registry(tmp_path, REGISTRY_BIRD)
    reg = load_registry(p)
    assert set(reg.keys()) == {"bird", "clue_a"}
    assert isinstance(reg["bird"], AssetEntry)
    assert reg["bird"].moodboard == "m7458053701014388751"
    assert reg["clue_a"].oref == "https://cdn/oref.png"
    assert reg["clue_a"].ow == 400


def test_registry_missing_subject_raises(tmp_path):
    p = _write_registry(tmp_path, {"bad": {"sref": "x"}})
    with pytest.raises(ValueError, match="subject"):
        load_registry(p)


def test_registry_file_missing_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_registry(tmp_path / "nope.json")


# --------------------- CLI dry-run ---------------------


def test_dry_run_composes_and_logs(tmp_path):
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_BIRD)
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(run(
        asset_id="bird",
        registry_path=reg_path,
        upscale=None,
        bridge_url="http://127.0.0.1:9999",  # unreachable; not hit in dry-run
        log_path=log_path,
        dry_run=True,
    ))

    assert result["ok"] is True
    assert result["asset_id"] == "bird"
    assert "--p m7458053701014388751" in result["prompt"]
    assert "transparent background" in result["prompt"]
    assert result["dry_run"] is True

    # Log got a record with agent_decision=dry_run. The log is JSON Lines
    # (one record per line), so parse line-by-line — reviewer-flagged bug.
    records = [
        json.loads(line)
        for line in log_path.read_text().splitlines()
        if line.strip()
    ]
    assert len(records) == 1
    assert records[0]["agent_decision"] == "dry_run"
    assert records[0]["asset_id"] == "bird"

    tags = _tags()
    assert "CLI_ROLL_STARTED" in tags
    assert "CLI_ROLL_COMPLETED" in tags
    assert "PROMPT_COMPOSED" in tags  # composer fired
    assert "PROMPT_LOGGED" in tags     # log fired


def test_unknown_asset_id_returns_structured_error(tmp_path):
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_BIRD)
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(run(
        asset_id="not_in_registry",
        registry_path=reg_path,
        upscale=None,
        bridge_url="http://127.0.0.1:9999",
        log_path=log_path,
        dry_run=True,
    ))

    assert result["ok"] is False
    assert result["error"]["code"] == "UNKNOWN_ASSET_ID"
    assert "bird" in result["error"]["remediation"]
    assert "CLI_ROLL_FAILED" in _tags()


def test_missing_registry_returns_structured_error(tmp_path):
    clear()
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(run(
        asset_id="bird",
        registry_path=tmp_path / "does-not-exist.json",
        upscale=None,
        bridge_url="http://127.0.0.1:9999",
        log_path=log_path,
        dry_run=True,
    ))

    assert result["ok"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert "CLI_ROLL_FAILED" in _tags()


def test_identity_lock_facets_flow_through(tmp_path):
    """clue_a has oref+ow set in the registry — the composed prompt must
    include --oref and --ow."""
    reg_path = _write_registry(tmp_path, REGISTRY_BIRD)
    result = asyncio.run(run(
        asset_id="clue_a",
        registry_path=reg_path,
        upscale=None,
        bridge_url="http://127.0.0.1:9999",
        log_path=tmp_path / "log.jsonl",
        dry_run=True,
    ))
    assert result["ok"] is True
    assert "--oref https://cdn/oref.png" in result["prompt"]
    assert "--ow 400" in result["prompt"]

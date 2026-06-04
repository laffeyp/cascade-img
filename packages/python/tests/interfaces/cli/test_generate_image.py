"""Behavior contract for the ``cascade-mj`` CLI.

Covers: registry loading, asset lookup, dry-run (full path without firing),
unknown asset_id structured error, malformed registry structured error.

Live-fire against a running bridge is not exercised by the unit test suite
— that's tools/smoke_mcp_walk.py against a real .env. The dry-run path
exercises compose + log without external state.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cascade_img.interfaces.cli.asset_registry import AssetEntry, load_registry
from cascade_img.interfaces.cli.generate_image import run
from cascade_img.vocabulary import clear, snapshot

REGISTRY_SAMPLE = {
    "mountain-icon": {
        "subject": "a flat-design icon of a mountain, centered",
        "constraints": ["transparent background"],
        "moodboard": "m1234567890123456789",
        "sref": "https://cdn.midjourney.com/x/0_0.png",
        "aspect_ratio": "1:1",
    },
    "hero-portrait": {
        "subject": "a portrait of a hero, front view",
        "moodboard": "m1234567890123456789",
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
    p = _write_registry(tmp_path, REGISTRY_SAMPLE)
    reg = load_registry(p)
    assert set(reg.keys()) == {"mountain-icon", "hero-portrait"}
    assert isinstance(reg["mountain-icon"], AssetEntry)
    assert reg["mountain-icon"].moodboard == "m1234567890123456789"
    assert reg["hero-portrait"].oref == "https://cdn/oref.png"
    assert reg["hero-portrait"].ow == 400


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
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(
        run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",  # unreachable; not hit in dry-run
            log_path=log_path,
            dry_run=True,
        )
    )

    assert result["ok"] is True
    assert result["asset_id"] == "mountain-icon"
    assert "--p m1234567890123456789" in result["prompt"]
    assert "transparent background" in result["prompt"]
    assert result["dry_run"] is True

    # Log got a record with agent_decision=dry_run. The log is JSON Lines
    # (one record per line), so parse line-by-line — reviewer-flagged bug.
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    assert records[0]["agent_decision"] == "dry_run"
    assert records[0]["asset_id"] == "mountain-icon"

    tags = _tags()
    assert "CLI_ROLL_STARTED" in tags
    assert "CLI_ROLL_COMPLETED" in tags
    assert "PROMPT_COMPOSED" in tags  # composer fired
    assert "PROMPT_LOGGED" in tags  # log fired


def test_unknown_asset_id_returns_structured_error(tmp_path):
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(
        run(
            asset_id="not_in_registry",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=log_path,
            dry_run=True,
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "UNKNOWN_ASSET_ID"
    assert "mountain-icon" in result["error"]["remediation"]
    assert "CLI_ROLL_FAILED" in _tags()


def test_missing_registry_returns_structured_error(tmp_path):
    clear()
    log_path = tmp_path / "log.jsonl"

    result = asyncio.run(
        run(
            asset_id="mountain-icon",
            registry_path=tmp_path / "does-not-exist.json",
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=log_path,
            dry_run=True,
        )
    )

    assert result["ok"] is False
    assert result["error"]["code"] == "FileNotFoundError"
    assert "CLI_ROLL_FAILED" in _tags()


def test_identity_lock_facets_flow_through(tmp_path):
    """hero-portrait has oref+ow set in the registry — the composed prompt must
    include --oref and --ow."""
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    result = asyncio.run(
        run(
            asset_id="hero-portrait",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "log.jsonl",
            dry_run=True,
        )
    )
    assert result["ok"] is True
    assert "--oref https://cdn/oref.png" in result["prompt"]
    assert "--ow 400" in result["prompt"]


# --------------------- CLI live path (stubbed backend) ---------------------


def test_non_dry_run_dispatches_sync_backend_via_to_thread(tmp_path, monkeypatch):
    """The CLI's non-dry-run path used to ``await`` the synchronous backend
    methods, which would raise ``TypeError: object dict can't be used in await
    expression`` against the real backend (synchronous since the 2026-06-02
    revision). Verify the path wraps the call in ``asyncio.to_thread`` so a
    sync backend works end-to-end.
    """
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    log_path = tmp_path / "log.jsonl"

    calls: list[tuple[str, tuple, dict]] = []

    class _StubSyncBackend:
        """Mirrors MidjourneyDiscordBackend's sync method signatures."""

        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def imagine(self, prompt, asset_id, upscale=None):
            calls.append(("imagine", (prompt, asset_id, upscale), {}))
            return {"job_id": "stub-job-1", "asset_id": asset_id, "status": "submitted"}

        def wait(self, job_id, timeout=180):
            calls.append(("wait", (job_id, timeout), {}))
            return {
                "status": "done",
                "image_path": "/tmp/stub.png",
                "grid_path": None,
                "upscale_paths": {},
            }

    import cascade_img.interfaces.cli.generate_image as cli_mod

    monkeypatch.setattr(cli_mod, "MidjourneyDiscordBackend", _StubSyncBackend)

    result = asyncio.run(
        cli_mod.run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=log_path,
            dry_run=False,
        )
    )

    assert result["ok"] is True
    assert result["job_id"] == "stub-job-1"
    assert result["status"] == "done"
    # The synchronous backend methods were actually invoked — no TypeError.
    assert [c[0] for c in calls] == ["imagine", "wait"]
    # Log captured the live-path record.
    records = [json.loads(line) for line in log_path.read_text().splitlines() if line.strip()]
    assert len(records) == 1
    assert records[0]["job_id"] == "stub-job-1"

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
        "version": "7",  # Omni Reference (oref) is V7-only
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


def test_identity_lock_parts_flow_through(tmp_path):
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


# --------------------- failure-path contracts (review remediation) ---------


def test_failed_wait_returns_structured_error_with_code(tmp_path, monkeypatch):
    """On a real job failure (status=='failed') the CLI must return the bridge's
    stable error_code inside a {code, message, remediation} envelope — NOT the
    bridge's bare error string, which drops the code a caller branches on. Every
    other error path and the module docstring promise the structured shape; this
    failed-wait path is the one the suite never exercised. (review #1)"""
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    log_path = tmp_path / "log.jsonl"

    class _FailingBackend:
        def __init__(self, base_url: str) -> None:
            self.base_url = base_url

        def imagine(self, prompt, asset_id, upscale=None):
            return {"job_id": "job-fail", "asset_id": asset_id, "status": "submitted"}

        def wait(self, job_id, timeout=180):
            return {
                "status": "failed",
                "error": "discord 400: This command is outdated",
                "error_code": "DISCORD_400_OUTDATED",
                "image_path": None,
                "grid_path": None,
                "upscale_paths": {},
            }

    import cascade_img.interfaces.cli.generate_image as cli_mod

    monkeypatch.setattr(cli_mod, "MidjourneyDiscordBackend", _FailingBackend)

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

    assert result["ok"] is False
    assert result["status"] == "failed"
    # The structured envelope carries the stable code, not the bare error string.
    assert isinstance(result["error"], dict)
    assert result["error"]["code"] == "DISCORD_400_OUTDATED"
    assert "outdated" in result["error"]["message"]
    assert "remediation" in result["error"]
    assert "CLI_ROLL_COMPLETED" in _tags()


def test_done_wait_carries_null_error(tmp_path, monkeypatch):
    """The happy path's error key is None (not the bare string), mirroring the
    corrected docstring. (review #1 / #11)"""
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)

    class _DoneBackend:
        def __init__(self, base_url: str) -> None: ...

        def imagine(self, prompt, asset_id, upscale=None):
            return {"job_id": "job-ok", "status": "submitted"}

        def wait(self, job_id, timeout=180):
            return {"status": "done", "image_path": "/tmp/x.png", "error": None}

    import cascade_img.interfaces.cli.generate_image as cli_mod

    monkeypatch.setattr(cli_mod, "MidjourneyDiscordBackend", _DoneBackend)
    result = asyncio.run(
        cli_mod.run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "log.jsonl",
            dry_run=False,
        )
    )
    assert result["ok"] is True
    assert result["error"] is None


def test_sw_stylize_coerced_to_int(tmp_path):
    """sw/stylize accept stringified numbers (registries are hand-edited JSON)
    and reach the composer as ints, not raw strings — the loader previously
    passed them through un-coerced, unlike ow/aspect_ratio. (review #9)"""
    p = _write_registry(tmp_path, {"icon": {"subject": "an icon", "sw": "50", "stylize": "250"}})
    reg = load_registry(p)
    assert reg["icon"].sw == 50 and isinstance(reg["icon"].sw, int)
    assert reg["icon"].stylize == 250 and isinstance(reg["icon"].stylize, int)


def test_non_numeric_sw_rejected_at_load(tmp_path):
    """A non-numeric sw fails at load time (where load_registry wraps it into the
    ValueError the CLI envelopes) rather than crashing the composer with a raw
    traceback downstream. (review #9)"""
    p = _write_registry(tmp_path, {"icon": {"subject": "an icon", "sw": "huge"}})
    with pytest.raises(ValueError, match="icon"):
        load_registry(p)


def test_compose_failure_is_enveloped(tmp_path, monkeypatch):
    """A registry the loader accepted can still carry a value the composer
    rejects; _compose() must run inside the envelope so the CLI returns a
    structured CLI_ROLL_FAILED rather than crashing with a raw traceback.
    (review #9)"""
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)
    import cascade_img.interfaces.cli.generate_image as cli_mod

    def _boom(entry):
        raise ValueError("composer rejected a param")

    monkeypatch.setattr(cli_mod, "_compose", _boom)

    result = asyncio.run(
        cli_mod.run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "log.jsonl",
            dry_run=True,
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "ValueError"
    assert "composer rejected" in result["error"]["message"]
    assert "CLI_ROLL_FAILED" in _tags()


# --------------------- main() argparse + exit-code contract ---------------------


def test_cli_main_dry_run_exits_0_and_prints_envelope(tmp_path, monkeypatch, capsys):
    """main() parses argv, runs the dry-run path, prints the JSON envelope, and
    exits 0 on success — the shipped `cascade-mj` entry point, not just run()."""
    import sys

    from cascade_img.interfaces.cli.generate_image import main

    reg = _write_registry(tmp_path, {"icon": {"subject": "a flat mountain icon"}})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cascade-mj",
            "icon",
            "--registry",
            str(reg),
            "--dry-run",
            "--log",
            str(tmp_path / "log.jsonl"),
            "--pretty",
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["asset_id"] == "icon"


def test_cli_main_unknown_asset_exits_1(tmp_path, monkeypatch, capsys):
    """main() exits non-zero and prints a structured error when the asset_id is
    not in the registry — the CLI exit-code contract (0 ok / 1 failure)."""
    import sys

    from cascade_img.interfaces.cli.generate_image import main

    reg = _write_registry(tmp_path, {"icon": {"subject": "a flat mountain icon"}})
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "cascade-mj",
            "nope",
            "--registry",
            str(reg),
            "--dry-run",
            "--log",
            str(tmp_path / "l.jsonl"),
        ],
    )
    with pytest.raises(SystemExit) as exc:
        main()
    assert exc.value.code == 1
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is False
    assert out["error"]["code"] == "UNKNOWN_ASSET_ID"


def test_imagine_raises_returns_structured_error(tmp_path, monkeypatch):
    """When backend.imagine() itself RAISES (bridge unreachable / requests error),
    the CLI envelopes it as CLI_ROLL_FAILED with the bridge-unreachable
    remediation — the exception branch the returned-'failed' test doesn't reach."""
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)

    class _UnreachableBackend:
        def __init__(self, base_url: str) -> None: ...

        def imagine(self, prompt, asset_id, upscale=None):
            raise ConnectionError("bridge down")

    import cascade_img.interfaces.cli.generate_image as cli_mod

    monkeypatch.setattr(cli_mod, "MidjourneyDiscordBackend", _UnreachableBackend)
    result = asyncio.run(
        cli_mod.run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "log.jsonl",
            dry_run=False,
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "ConnectionError"
    assert "cascade-mj-bridge --doctor" in result["error"]["remediation"]
    assert "CLI_ROLL_FAILED" in _tags()


def test_wait_raises_returns_structured_error_with_job_id(tmp_path, monkeypatch):
    """When backend.wait() RAISES after a successful submit, the CLI envelopes it
    and still reports the job_id (so the caller can recover the in-flight job
    rather than resubmit) — the second exception branch."""
    clear()
    reg_path = _write_registry(tmp_path, REGISTRY_SAMPLE)

    class _WaitBoomBackend:
        def __init__(self, base_url: str) -> None: ...

        def imagine(self, prompt, asset_id, upscale=None):
            return {"job_id": "job-boom", "asset_id": asset_id, "status": "submitted"}

        def wait(self, job_id, timeout=180):
            raise TimeoutError("read timed out")

    import cascade_img.interfaces.cli.generate_image as cli_mod

    monkeypatch.setattr(cli_mod, "MidjourneyDiscordBackend", _WaitBoomBackend)
    result = asyncio.run(
        cli_mod.run(
            asset_id="mountain-icon",
            registry_path=reg_path,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "log.jsonl",
            dry_run=False,
        )
    )
    assert result["ok"] is False
    assert result["error"]["code"] == "TimeoutError"
    assert result["job_id"] == "job-boom"
    assert "CLI_ROLL_FAILED" in _tags()


# --------------------- registry expresses the full V8.1 surface (review G1/G2) --


def test_registry_full_v8_surface_threads_to_prompt(tmp_path):
    """A registry entry exercising the full V8.1 render-control + content surface
    threads every part through _compose into the prompt. Closes the gap where the
    registry could previously express only hd/sd of the render controls (the
    --no/--chaos/--weird/--tile/--exp/--seed/--iw/image-prompt fields were
    unreachable from a registry roll), and pins the registry hd thread that had
    no test. (review #4 G1/G2)"""
    clear()
    reg = _write_registry(
        tmp_path,
        {
            "rich": {
                "subject": "a flat icon",
                "constraints": ["centered"],
                "negatives": ["text", "watermark"],
                "image_prompts": ["https://cdn/ref.png"],
                "image_weight": 2.0,
                "tile": True,
                "exp": 15,
                "chaos": 10,
                "weird": 50,
                "seed": 42,
                "hd": True,
            }
        },
    )
    result = asyncio.run(
        run(
            asset_id="rich",
            registry_path=reg,
            upscale=None,
            bridge_url="http://127.0.0.1:9999",
            log_path=tmp_path / "l.jsonl",
            dry_run=True,
        )
    )
    assert result["ok"] is True
    p = result["prompt"]
    for frag in ["--hd", "--chaos 10", "--weird 50", "--tile", "--exp 15", "--seed 42", "--iw 2.0"]:
        assert frag in p, f"{frag} missing from {p!r}"
    assert p.startswith("https://cdn/ref.png ")  # image prompt leads the prompt
    assert p.rstrip().endswith("--no text, watermark")  # --no stays the final flag
    assert "--v 8.1" in p  # default model


def test_registry_loads_full_surface_fields(tmp_path):
    """The loader coerces every new field to its declared type (lists, float iw,
    int render controls) so a malformed value fails at load, not mid-render."""
    reg = load_registry(
        _write_registry(
            tmp_path,
            {
                "a": {
                    "subject": "x",
                    "image_weight": "1.5",
                    "chaos": "10",
                    "seed": "42",
                    "tile": True,
                }
            },
        )
    )
    e = reg["a"]
    assert e.image_weight == 1.5 and isinstance(e.image_weight, float)
    assert e.chaos == 10 and e.seed == 42 and e.tile is True

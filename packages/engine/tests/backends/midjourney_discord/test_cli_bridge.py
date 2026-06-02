"""Behavior contract for the bridge CLI subcommands (--check-env / --doctor).

Calls the functions directly. Subprocess-level tests of the CLI argv path
would catch argument parsing regressions, but the structured payload is what
the LLM operator branches on — verifying that here keeps tests fast and
isolated.
"""

from __future__ import annotations

from cascade_img.backends.midjourney_discord.bridge import check_env, doctor
from cascade_img.instrumentation.runtime import clear, snapshot

VALID = {
    "DISCORD_USER_TOKEN": "MTU.fake.token.with.some.length",
    "MJ_CHANNEL_ID": "123456789012345678",
    "MJ_IMAGINE_VERSION": "1234567890123456789",
}


def _scrub(monkeypatch):
    for k in (
        "DISCORD_USER_TOKEN",
        "MJ_CHANNEL_ID",
        "MJ_GUILD_ID",
        "MJ_IMAGINE_VERSION",
        "MJ_IMAGINE_COMMAND_ID",
        "MJ_OUTPUT_DIR",
        "PORT",
    ):
        monkeypatch.delenv(k, raising=False)


def _tags():
    return [r["tag"] for r in snapshot()]


# --------------------- check_env ---------------------


def test_check_env_returns_structured_error_when_missing_vars(monkeypatch, tmp_path):
    clear()
    _scrub(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = check_env()
    assert result["ok"] is False
    assert "code" in result["error"]
    assert "remediation" in result["error"]
    assert result["error"]["code"] == "MISSING_DISCORD_TOKEN"
    assert "BRIDGE_CHECKENV_RAN" in _tags()


def test_check_env_returns_ok_with_masked_token(monkeypatch, tmp_path):
    clear()
    _scrub(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MJ_OUTPUT_DIR", str(tmp_path / "out"))
    result = check_env()
    assert result["ok"] is True
    # Token is reported as present + length, never the value.
    assert result["config"]["discord_token_present"] is True
    assert result["config"]["discord_token_len"] == len(VALID["DISCORD_USER_TOKEN"])
    assert "discord_token" not in result["config"]
    assert result["config"]["channel_id"] == int(VALID["MJ_CHANNEL_ID"])
    assert result["config"]["guild_id"] is None
    assert result["config"]["port"] == 5000


# --------------------- doctor ---------------------


def test_doctor_reports_all_checks(monkeypatch, tmp_path):
    """Doctor must always return a checks list with the four known checks,
    pass or fail."""
    clear()
    _scrub(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MJ_OUTPUT_DIR", str(tmp_path / "out"))
    result = doctor()
    names = [c["name"] for c in result["checks"]]
    assert "env" in names
    assert "discord_reachable" in names
    assert "mcp_server_importable" in names
    assert "discord_self_importable" in names
    # Three of four are always pure-import checks; env passes here too.
    # discord_reachable may fail in restricted networks; not asserting it.
    assert "BRIDGE_DOCTOR_RAN" in _tags()


def test_doctor_env_check_fails_cleanly_on_empty(monkeypatch, tmp_path):
    clear()
    _scrub(monkeypatch)
    monkeypatch.chdir(tmp_path)
    result = doctor()
    env_check = next(c for c in result["checks"] if c["name"] == "env")
    assert env_check["ok"] is False
    assert env_check["error"]["code"] == "MISSING_DISCORD_TOKEN"
    # The overall result.ok is False because env failed.
    assert result["ok"] is False

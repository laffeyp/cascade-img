"""Behavior contract for Config.from_env() + MissingEnvError.

Captures the boot-phase signal sequence for the load-bearing failure modes
the LLM operator has to be able to recover from:
- missing DISCORD_USER_TOKEN
- missing MJ_CHANNEL_ID
- invalid MJ_CHANNEL_ID (non-integer)
- missing MJ_IMAGINE_VERSION
- happy path

Each test asserts both the structured error payload (code + remediation,
the things an LLM branches on) and the emitted signal sequence (the dual
contract — code says the right thing and the program speaks the right thing).
"""

from __future__ import annotations

import pytest

from cascade_img.backends.midjourney_discord.bridge import Config, MissingEnvError
from cascade_img.vocabulary import clear, snapshot

VALID_ENV = {
    "DISCORD_USER_TOKEN": "MTU.fake.token",
    "MJ_CHANNEL_ID": "123456789012345678",
    "MJ_IMAGINE_VERSION": "1234567890123456789",
    # MJ_IMAGINE_COMMAND_ID has a default; not required
    "PORT": "5000",
}


def _scrub_env(monkeypatch):
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


def _tag_sequence() -> list[str]:
    return [r["tag"] for r in snapshot()]


def test_missing_discord_token_raises_structured(monkeypatch, tmp_path):
    """No DISCORD_USER_TOKEN -> MissingEnvError(MISSING_DISCORD_TOKEN) + nothing emitted yet."""
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)  # avoid .env discovery

    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "MISSING_DISCORD_TOKEN"
    assert "DISCORD_USER_TOKEN" in exc.value.message
    assert "RUNBOOK.md" in exc.value.remediation
    # The CONFIG_VALIDATED tag must NOT have fired.
    assert "CONFIG_VALIDATED" not in _tag_sequence()


def test_missing_channel_id_raises_structured(monkeypatch, tmp_path):
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_USER_TOKEN", VALID_ENV["DISCORD_USER_TOKEN"])

    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "MISSING_CHANNEL_ID"
    assert "CONFIG_VALIDATED" not in _tag_sequence()


def test_invalid_channel_id_raises_structured(monkeypatch, tmp_path):
    """Non-integer channel ID is a stable error code, not a ValueError."""
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_USER_TOKEN", VALID_ENV["DISCORD_USER_TOKEN"])
    monkeypatch.setenv("MJ_CHANNEL_ID", "not-a-number")

    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "INVALID_CHANNEL_ID"


def test_port_too_low_raises_invalid_port(monkeypatch, tmp_path):
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PORT", "0")
    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "INVALID_PORT"


def test_port_too_high_raises_invalid_port(monkeypatch, tmp_path):
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("PORT", "99999")
    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "INVALID_PORT"


def test_missing_imagine_version_raises_structured(monkeypatch, tmp_path):
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("DISCORD_USER_TOKEN", VALID_ENV["DISCORD_USER_TOKEN"])
    monkeypatch.setenv("MJ_CHANNEL_ID", VALID_ENV["MJ_CHANNEL_ID"])

    with pytest.raises(MissingEnvError) as exc:
        Config.from_env()
    assert exc.value.code == "MISSING_IMAGINE_VERSION"


def test_happy_path_emits_config_validated(monkeypatch, tmp_path):
    """All required vars set -> Config returned, CONFIG_VALIDATED emitted once
    with has_guild_id=False (no guild id supplied)."""
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MJ_OUTPUT_DIR", str(tmp_path / "generated"))

    cfg = Config.from_env()

    assert cfg.channel_id == int(VALID_ENV["MJ_CHANNEL_ID"])
    assert cfg.port == 5000
    assert cfg.guild_id is None
    # signal contract
    tags = _tag_sequence()
    assert tags == ["CONFIG_VALIDATED"], f"expected exactly [CONFIG_VALIDATED], got {tags}"
    payload = snapshot()[0]["payload"]
    assert payload["has_guild_id"] is False
    assert payload["port"] == 5000


def test_happy_path_with_guild_id_emits_has_guild_id_true(monkeypatch, tmp_path):
    """MJ_GUILD_ID set -> CONFIG_VALIDATED.has_guild_id=True (the the default patch)."""
    clear()
    _scrub_env(monkeypatch)
    monkeypatch.chdir(tmp_path)
    for k, v in VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MJ_GUILD_ID", "987654321098765432")
    monkeypatch.setenv("MJ_OUTPUT_DIR", str(tmp_path / "generated"))

    cfg = Config.from_env()

    assert cfg.guild_id == "987654321098765432"
    payload = snapshot()[0]["payload"]
    assert payload["has_guild_id"] is True

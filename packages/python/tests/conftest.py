"""Shared pytest fixtures for cascade-img.

Centralizes the env-scrubbing pattern that several test modules need (Config
behavior tests, --check-env / --doctor tests). Each test that touches the
environment depends on ``scrubbed_env`` so the env vars are guaranteed-clean
at function entry; tests that want a happy-path config use ``valid_env``.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest

# All env vars cascade-img's Config reads. Test fixtures clear these before
# every dependent test so a stray developer-machine env doesn't leak in.
_CASCADE_ENV_VARS = (
    "DISCORD_USER_TOKEN",
    "MJ_CHANNEL_ID",
    "MJ_GUILD_ID",
    "MJ_IMAGINE_VERSION",
    "MJ_IMAGINE_COMMAND_ID",
    "MJ_OUTPUT_DIR",
    "PORT",
)


_VALID_ENV = {
    "DISCORD_USER_TOKEN": "MTU.fake.token.for.tests",
    "MJ_CHANNEL_ID": "123456789012345678",
    "MJ_IMAGINE_VERSION": "1234567890123456789",
    "PORT": "5000",
}


@pytest.fixture
def scrubbed_env(monkeypatch, tmp_path) -> Iterator[None]:
    """Delete every Config-relevant env var and chdir to a tmp dir so no
    stray ``.env`` is discovered."""
    for k in _CASCADE_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    yield


@pytest.fixture
def valid_env(monkeypatch, tmp_path) -> Iterator[dict[str, str]]:
    """A scrubbed env populated with the minimum vars Config.from_env()
    needs to return a Config object. Tests get a copy of the dict so they
    can read back the values they set."""
    for k in _CASCADE_ENV_VARS:
        monkeypatch.delenv(k, raising=False)
    monkeypatch.chdir(tmp_path)
    for k, v in _VALID_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("MJ_OUTPUT_DIR", str(tmp_path / "generated"))
    yield dict(_VALID_ENV)

"""Bridge configuration and runtime constants.

Owns the ``Config`` dataclass, the module-level ``cfg`` holder, the ``_cfg()``
accessor, and the daemon's tuning/identity constants.

Binding discipline: ``cfg`` is reassigned at startup. Read it only via
``_cfg()`` (which reads this module's global); set it via attribute assignment
on this module — ``config.cfg = Config.from_env()`` — never ``from .config
import cfg`` (that would bind the ``None`` placeholder).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import find_dotenv, load_dotenv

from cascade_img.backends.midjourney_discord.errors import MissingEnvError
from cascade_img.vocabulary import emit

# Eviction configuration. Overridable via env at startup so deployments can
# tune for their own job-rate / memory profile.
MAX_JOBS = int(os.environ.get("CASCADE_MAX_JOBS", "1000"))
TERMINAL_AGE_SECONDS = float(os.environ.get("CASCADE_TERMINAL_AGE_SECONDS", "3600"))
# A non-terminal job whose updated_at hasn't advanced within this window is
# treated as stalled and failed RESUBMIT_REQUIRED by the reaper (see
# _reap_stalled_jobs). updated_at is touched on every progress edit / slot
# landing, so this is "max silence", not "max total duration": a healthy
# upscale="all" job that is actively progressing never trips it. Generous by
# default (15 min of total silence) so only genuine stalls are reaped.
INFLIGHT_TIMEOUT_SECONDS = float(os.environ.get("CASCADE_INFLIGHT_TIMEOUT_SECONDS", "900"))


PACKAGE_VERSION = "0.1.0"  # bumped in lock-step with pyproject.toml
BACKEND_NAME = "midjourney_discord"


# Midjourney's public, well-known Discord application ID — the same for every MJ
# user, so it's a fixed constant here, not per-operator config.
MJ_BOT_ID = 936929561302675456


@dataclass
class Config:
    """Daemon configuration. Constructed via :meth:`from_env`."""

    discord_token: str
    channel_id: int
    # Required when the MJ channel lives in a guild; Discord 400s otherwise.
    guild_id: str | None
    mj_imagine_version: str
    mj_imagine_command_id: str
    output_dir: Path
    port: int

    @classmethod
    def from_env(cls) -> Config:
        """Read and validate every env var; raise MissingEnvError on the first gap."""
        # Anchor the .env search at the cwd: under the console-script entry point
        # ``find_dotenv()`` would walk up from the installed package, not the cwd.
        # ``CASCADE_DOTENV`` lets an operator point at the file explicitly instead.
        dotenv_override = os.environ.get("CASCADE_DOTENV")
        if dotenv_override:
            load_dotenv(dotenv_override)
        else:
            load_dotenv(find_dotenv(usecwd=True))

        def _require(name: str, code: str, remediation: str) -> str:
            val = os.environ.get(name)
            if not val:
                raise MissingEnvError(
                    code,
                    f"environment variable {name} is not set",
                    remediation,
                )
            return val

        discord_token = _require(
            "DISCORD_USER_TOKEN",
            "MISSING_DISCORD_TOKEN",
            "Add DISCORD_USER_TOKEN to .env; see RUNBOOK.md for the "
            "devtools-capture procedure. Treat the value as a password.",
        )
        channel_id_raw = _require(
            "MJ_CHANNEL_ID",
            "MISSING_CHANNEL_ID",
            "Add MJ_CHANNEL_ID to .env. Enable Discord Developer Mode "
            "(Settings -> Advanced) then right-click the MJ channel -> Copy Channel ID.",
        )
        try:
            channel_id = int(channel_id_raw)
        except ValueError as e:
            raise MissingEnvError(
                "INVALID_CHANNEL_ID",
                f"MJ_CHANNEL_ID is not a valid integer: {channel_id_raw!r}",
                "MJ_CHANNEL_ID must be the 18-19 digit channel ID from Discord. "
                "Re-capture per RUNBOOK.md.",
            ) from e

        # Optional: required only when the MJ channel lives in a guild.
        guild_id = os.environ.get("MJ_GUILD_ID") or None

        mj_imagine_version = _require(
            "MJ_IMAGINE_VERSION",
            "MISSING_IMAGINE_VERSION",
            "Add MJ_IMAGINE_VERSION to .env. Re-capture from desktop Discord "
            "DevTools whenever MJ updates the slash command (you'll see "
            "'discord 400: This command is outdated'). See RUNBOOK.md.",
        )
        mj_imagine_command_id = os.environ.get("MJ_IMAGINE_COMMAND_ID", "938956540159881230")

        output_dir = Path(os.environ.get("MJ_OUTPUT_DIR", "./generated")).resolve()
        output_dir.mkdir(parents=True, exist_ok=True)

        try:
            port = int(os.environ.get("PORT", "5000"))
            if not (1 <= port <= 65535):
                raise ValueError(f"port must be 1-65535, got {port}")
        except ValueError as e:
            raise MissingEnvError(
                "INVALID_PORT",
                f"PORT must be a valid integer 1-65535: {os.environ.get('PORT')!r}",
                "PORT defaults to 5000. Set a positive integer 1-65535 or leave unset.",
            ) from e

        emit(
            "CONFIG_VALIDATED",
            port=port,
            output_dir=str(output_dir),
            has_guild_id=bool(guild_id),
        )
        return cls(
            discord_token=discord_token,
            channel_id=channel_id,
            guild_id=guild_id,
            mj_imagine_version=mj_imagine_version,
            mj_imagine_command_id=mj_imagine_command_id,
            output_dir=output_dir,
            port=port,
        )


# Module-level Config holder. Set by :func:`bridge.main` (or by an embedding
# caller) before the Discord event loop or Flask app are started, via
# ``config.cfg = Config.from_env()``.
cfg: Config | None = None


def _cfg() -> Config:
    """Return the loaded Config, asserting it was set at startup."""
    if cfg is None:
        raise RuntimeError(
            "config.cfg is not set — call Config.from_env() and assign to "
            "config.cfg before starting the daemon."
        )
    return cfg

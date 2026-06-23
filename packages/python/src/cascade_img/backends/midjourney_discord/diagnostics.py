"""Pre-flight diagnostics for the bridge CLI: ``--check-env`` and ``--doctor``.

These run *without* starting the
daemon or connecting to Discord — they validate config, network reachability,
and importability so an operator can debug bring-up before the daemon owns the
process. The running daemon's ``/health`` route covers live state.
"""

from __future__ import annotations

import importlib
import logging

import requests

from cascade_img.backends.midjourney_discord.config import Config
from cascade_img.backends.midjourney_discord.errors import MissingEnvError
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.diagnostics")


def check_env() -> dict:
    """Validate the environment without starting anything. Returns a
    structured dict with ``ok`` and either ``config`` (the loaded fields,
    secrets masked) or ``error`` (code + remediation).
    """

    try:
        c = Config.from_env()
    except MissingEnvError as e:
        emit(
            "BRIDGE_CHECKENV_RAN",
            ok=False,
            error_code=e.code,
        )
        return {
            "ok": False,
            "error": e.to_payload(),
        }
    emit("BRIDGE_CHECKENV_RAN", ok=True, error_code="")
    return {
        "ok": True,
        "config": {
            # mask the token by length so the operator can see something is
            # there without leaking it
            "discord_token_present": bool(c.discord_token),
            "discord_token_len": len(c.discord_token),
            "channel_id": c.channel_id,
            "guild_id": c.guild_id,
            "mj_imagine_version": c.mj_imagine_version,
            "mj_imagine_command_id": c.mj_imagine_command_id,
            "output_dir": str(c.output_dir),
            "port": c.port,
        },
    }


def doctor() -> dict:
    """Full validation: env, Discord API reachability, MCP server importable,
    bridge-side imports clean. Returns a list of checks with per-check
    pass/fail/remediation.

    Does NOT start the daemon or connect to Discord — those are side-effecty
    and require live MJ. Use ``--doctor`` for the pre-flight; use the running
    daemon's ``/health`` for live-state.
    """
    checks: list[dict] = []

    # check 1: env
    env_result = check_env()
    checks.append(
        {
            "name": "env",
            "ok": env_result["ok"],
            **(
                {"detail": env_result["config"]}
                if env_result["ok"]
                else {"error": env_result["error"]}
            ),
        }
    )

    # check 2: discord.com reachability (no token needed; just network)
    try:
        r = requests.get("https://discord.com/api/v9/gateway", timeout=5)
        checks.append(
            {
                "name": "discord_reachable",
                "ok": r.status_code == 200,
                "status": r.status_code,
            }
        )
    except Exception as e:
        checks.append(
            {
                "name": "discord_reachable",
                "ok": False,
                "error": {"code": "DISCORD_UNREACHABLE", "message": str(e)},
            }
        )

    try:
        importlib.import_module("cascade_img.interfaces.mcp.tool_server")
        checks.append({"name": "mcp_server_importable", "ok": True})
    except Exception as e:
        checks.append(
            {
                "name": "mcp_server_importable",
                "ok": False,
                "error": {"code": "MCP_IMPORT_FAILED", "message": str(e)},
            }
        )

    try:
        importlib.import_module("discord")
        checks.append({"name": "discord_self_importable", "ok": True})
    except Exception as e:
        checks.append(
            {
                "name": "discord_self_importable",
                "ok": False,
                "error": {"code": "DISCORD_SELF_IMPORT_FAILED", "message": str(e)},
            }
        )

    ok = all(c["ok"] for c in checks)
    emit(
        "BRIDGE_DOCTOR_RAN",
        ok=ok,
        checks_total=len(checks),
        checks_failed=sum(1 for c in checks if not c["ok"]),
    )
    return {"ok": ok, "checks": checks}

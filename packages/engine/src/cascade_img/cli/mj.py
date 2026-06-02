"""``cascade-mj`` — unified roll-and-log CLI for the Midjourney backend.

Usage::

    cascade-mj <asset_id> --registry path/to/assets.json [options]

Options:
  --upscale {grid,1,2,3,4,all}   Upscale mode (default: grid)
  --bridge-url URL               Bridge daemon URL (default $CASCADE_BRIDGE_URL or 127.0.0.1:5000)
  --log PATH                     Prompt log JSONL path (default $CASCADE_PROMPT_LOG or ./cascade-prompt-log.jsonl)
  --dry-run                      Compose the prompt and log it, but don't fire
  --pretty                       Indent JSON output

Output (JSON to stdout)::

    { "ok": true, "asset_id": "...", "prompt": "...", "job_id": "...", "status": "done",
      "outputs": {...}, "agent_decision": null, "agent_reason": null }

  on failure::

    { "ok": false, "asset_id": "...", "error": { "code": "...", "message": "...", "remediation": "..." } }
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend
from cascade_img.cli.registry import AssetEntry, load_registry
from cascade_img.composer import (
    IdentityStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.instrumentation.runtime import emit
from cascade_img.log import PromptLog


def _compose(entry: AssetEntry) -> str:
    return PromptComposer().compose(
        Subject(text=entry.subject, constraints=entry.constraints),
        style=StyleStack(
            moodboard=entry.moodboard,
            sref=entry.sref,
            stylize=entry.stylize,
            style_raw=entry.style_raw,
        ),
        identity=IdentityStack(oref=entry.oref, ow=entry.ow) if entry.oref else None,
        aspect_ratio=entry.aspect_ratio,
    )


async def run(
    asset_id: str,
    registry_path: Path,
    upscale: str | None,
    bridge_url: str,
    log_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Execute one roll-and-log. Returns the structured result dict."""
    emit("CLI_ROLL_STARTED", asset_id=asset_id, dry_run=dry_run, upscale=upscale or "grid")

    log = PromptLog(log_path)

    try:
        registry = load_registry(registry_path)
    except (FileNotFoundError, ValueError) as e:
        emit("CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__,
             error_message=str(e))
        return {
            "ok": False,
            "asset_id": asset_id,
            "error": {"code": type(e).__name__, "message": str(e)},
        }

    if asset_id not in registry:
        emit("CLI_ROLL_FAILED", asset_id=asset_id, error_code="UNKNOWN_ASSET_ID",
             error_message=f"asset_id {asset_id!r} not in registry")
        return {
            "ok": False,
            "asset_id": asset_id,
            "error": {
                "code": "UNKNOWN_ASSET_ID",
                "message": f"asset_id {asset_id!r} not in registry",
                "remediation": f"Available asset_ids: {sorted(registry.keys())}",
            },
        }

    entry = registry[asset_id]
    prompt = _compose(entry)

    if dry_run:
        log.append(
            asset_id=asset_id,
            prompt=prompt,
            backend="midjourney_discord",
            upscale=upscale,
            agent_decision="dry_run",
            agent_reason="--dry-run, did not fire",
        )
        emit("CLI_ROLL_COMPLETED", asset_id=asset_id, dry_run=True, status="dry_run")
        return {
            "ok": True,
            "asset_id": asset_id,
            "prompt": prompt,
            "dry_run": True,
        }

    backend = MidjourneyDiscordBackend(base_url=bridge_url)

    try:
        submitted = await backend.imagine(prompt, asset_id, upscale)
    except Exception as e:
        emit("CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__,
             error_message=str(e))
        log.append(
            asset_id=asset_id, prompt=prompt, backend="midjourney_discord",
            upscale=upscale, error=str(e),
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "prompt": prompt,
            "error": {"code": type(e).__name__, "message": str(e)},
        }

    job_id = submitted["job_id"]

    # Pick a timeout band based on upscale mode (matches the default calibration).
    timeout = 600 if upscale == "all" else (360 if upscale in {"1", "2", "3", "4"} else 180)

    try:
        result = await backend.wait(job_id, timeout=timeout)
    except Exception as e:
        emit("CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__,
             error_message=str(e))
        log.append(
            asset_id=asset_id, prompt=prompt, backend="midjourney_discord",
            job_id=job_id, upscale=upscale, error=str(e),
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "prompt": prompt,
            "job_id": job_id,
            "error": {"code": type(e).__name__, "message": str(e)},
        }

    outputs = {
        "image_path": result.get("image_path"),
        "grid_path": result.get("grid_path"),
        "upscale_paths": result.get("upscale_paths") or {},
    }
    log.append(
        asset_id=asset_id, prompt=prompt, backend="midjourney_discord",
        job_id=job_id, upscale=upscale,
        outputs=outputs,
        error=result.get("error"),
    )
    emit("CLI_ROLL_COMPLETED", asset_id=asset_id, dry_run=False,
         status=result.get("status", "unknown"))

    return {
        "ok": result.get("status") == "done",
        "asset_id": asset_id,
        "prompt": prompt,
        "job_id": job_id,
        "status": result.get("status"),
        "outputs": outputs,
        "error": result.get("error"),
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="cascade-mj")
    parser.add_argument("asset_id", help="ID of the asset to roll, must exist in the registry")
    parser.add_argument(
        "--registry",
        required=True,
        type=Path,
        help="Path to the JSON registry file (asset_id -> facets)",
    )
    parser.add_argument(
        "--upscale",
        choices=["grid", "1", "2", "3", "4", "all"],
        default="grid",
        help="Upscale mode (default: grid)",
    )
    parser.add_argument(
        "--bridge-url",
        default=os.environ.get("CASCADE_BRIDGE_URL", "http://127.0.0.1:5000"),
    )
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(os.environ.get("CASCADE_PROMPT_LOG", "./cascade-prompt-log.jsonl")),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Compose and log the prompt without firing /imagine",
    )
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args()

    # Normalize "grid" -> None for the backend (matches the bridge's API).
    upscale = None if args.upscale == "grid" else args.upscale

    result = asyncio.run(
        run(
            asset_id=args.asset_id,
            registry_path=args.registry,
            upscale=upscale,
            bridge_url=args.bridge_url,
            log_path=args.log,
            dry_run=args.dry_run,
        )
    )
    print(json.dumps(result, indent=2 if args.pretty else None, default=str))
    sys.exit(0 if result["ok"] else 1)


if __name__ == "__main__":
    main()

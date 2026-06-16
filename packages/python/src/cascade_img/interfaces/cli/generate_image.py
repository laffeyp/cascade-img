"""``cascade-mj`` — CLI for the Midjourney backend.

Composes a prompt from a registry asset, fires the generation against the
bridge daemon, waits for the result, and writes a record to the prompt log.

Usage::

    cascade-mj <asset_id> --registry path/to/assets.json [options]

Options:
  --upscale {grid,1,2,3,4,all}   Upscale mode (default: grid)
  --bridge-url URL               Bridge daemon URL (default $CASCADE_BRIDGE_URL or 127.0.0.1:5000)
  --log PATH                     Prompt log JSONL path (default $CASCADE_PROMPT_LOG or ./cascade-prompt-log.jsonl)
  --dry-run                      Compose the prompt and log it, but don't fire
  --pretty                       Indent JSON output

Output (JSON to stdout). Every return carries ``ok`` and ``asset_id``; the
other keys depend on how far the roll got before returning::

    success:   { "ok": true,  "asset_id", "prompt", "job_id", "status": "done",
                 "outputs": { "image_path", "grid_path", "upscale_paths" },
                 "error": null }
    dry-run:   { "ok": true,  "asset_id", "prompt", "dry_run": true }
    failure:   { "ok": false, "asset_id", "error": { "code", "message", "remediation" }, ... }

On failure, ``error`` is always the full ``{code, message, remediation}`` (the
stable ``code`` is the branch key); on success it is ``null``. The failure
return also gains ``prompt`` / ``job_id`` / ``status`` / ``outputs`` as the roll
reaches each — an early registry/compose failure has only ``error``; a failed
job after waiting has all of them.
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
from cascade_img.interfaces.cli.asset_registry import AssetEntry, load_registry
from cascade_img.prompt.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.prompt.prompt_log import PromptLog
from cascade_img.vocabulary import emit


def _compose(entry: AssetEntry) -> str:
    return PromptComposer().compose(
        Subject(
            text=entry.subject,
            constraints=entry.constraints,
            negatives=entry.negatives,
            image_prompts=entry.image_prompts,
            image_weight=entry.image_weight,
        ),
        style=StyleStack(
            moodboard=entry.moodboard,
            sref=entry.sref,
            sw=entry.sw,
            stylize=entry.stylize,
            style_raw=entry.style_raw,
        ),
        identity=IdentityStack(oref=entry.oref, ow=entry.ow) if entry.oref else None,
        params=ParamStack(
            tile=entry.tile,
            exp=entry.exp,
            chaos=entry.chaos,
            weird=entry.weird,
            quality=entry.quality,
            hd=entry.hd,
            sd=entry.sd,
            seed=entry.seed,
        ),
        aspect_ratio=entry.aspect_ratio,
        version=entry.version,
    )


async def run(
    asset_id: str,
    registry_path: Path,
    upscale: str | None,
    bridge_url: str,
    log_path: Path,
    dry_run: bool,
) -> dict[str, Any]:
    """Execute one generation end-to-end. Returns the structured result dict."""
    emit("CLI_ROLL_STARTED", asset_id=asset_id, dry_run=dry_run, upscale=upscale or "grid")

    log = PromptLog(log_path)

    try:
        registry = load_registry(registry_path)
    except (FileNotFoundError, ValueError) as e:
        emit(
            "CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__, error_message=str(e)
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "error": {
                "code": type(e).__name__,
                "message": str(e),
                "remediation": (
                    "Check the --registry path exists and is valid JSON mapping "
                    "asset_id -> prompt parts (subject required). See RUNBOOK.md."
                ),
            },
        }

    if asset_id not in registry:
        emit(
            "CLI_ROLL_FAILED",
            asset_id=asset_id,
            error_code="UNKNOWN_ASSET_ID",
            error_message=f"asset_id {asset_id!r} not in registry",
        )
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
    # Compose inside the envelope: a registry the loader accepted can still
    # carry a value the composer rejects (e.g. an out-of-range param), and
    # _compose() sitting outside any try would crash the CLI with a raw
    # traceback instead of the structured CLI_ROLL_FAILED error.
    try:
        prompt = _compose(entry)
    except Exception as e:
        emit(
            "CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__, error_message=str(e)
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "error": {
                "code": type(e).__name__,
                "message": str(e),
                "remediation": (
                    "The asset entry composed to an invalid prompt. Check its params "
                    "(sw/stylize/ow ranges, aspect_ratio) against CAPABILITIES.md."
                ),
            },
        }

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

    # MidjourneyDiscordBackend methods are synchronous (they call requests
    # directly); dispatch via to_thread so the async CLI doesn't block its
    # event loop on the HTTP call and so a missing await doesn't TypeError.
    try:
        submitted = await asyncio.to_thread(backend.imagine, prompt, asset_id, upscale)
    except Exception as e:
        emit(
            "CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__, error_message=str(e)
        )
        log.append(
            asset_id=asset_id,
            prompt=prompt,
            backend="midjourney_discord",
            upscale=upscale,
            error=str(e),
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "prompt": prompt,
            "error": {
                "code": type(e).__name__,
                "message": str(e),
                "remediation": (
                    "The bridge rejected or could not be reached for /imagine. Check it "
                    "is running and reachable at --bridge-url (cascade-mj-bridge --doctor)."
                ),
            },
        }

    job_id = submitted["job_id"]

    # Calibrated upper bounds: grid 180s, single upscale 360s, all four 600s.
    timeout = 600 if upscale == "all" else (360 if upscale in {"1", "2", "3", "4"} else 180)

    try:
        result = await asyncio.to_thread(backend.wait, job_id, timeout)
    except Exception as e:
        emit(
            "CLI_ROLL_FAILED", asset_id=asset_id, error_code=type(e).__name__, error_message=str(e)
        )
        log.append(
            asset_id=asset_id,
            prompt=prompt,
            backend="midjourney_discord",
            job_id=job_id,
            upscale=upscale,
            error=str(e),
        )
        return {
            "ok": False,
            "asset_id": asset_id,
            "prompt": prompt,
            "job_id": job_id,
            "error": {
                "code": type(e).__name__,
                "message": str(e),
                "remediation": (
                    f"The job was submitted but the wait failed (bridge unreachable "
                    f"mid-wait, or the job was evicted). Poll GET /status/{job_id} on the "
                    f"bridge; do NOT re-roll blindly — the original may still complete."
                ),
            },
        }

    outputs = {
        "image_path": result.get("image_path"),
        "grid_path": result.get("grid_path"),
        "upscale_paths": result.get("upscale_paths") or {},
    }
    log.append(
        asset_id=asset_id,
        prompt=prompt,
        backend="midjourney_discord",
        job_id=job_id,
        upscale=upscale,
        outputs=outputs,
        error=result.get("error"),
    )
    status = result.get("status")

    # /wait can return a non-terminal job: the bridge-side wait timed out
    # (backend marks timed_out=True on the 504) while MJ may still be rendering.
    # Without this branch the CLI returned ok=false / error=null — there was no
    # way for a caller to tell "the job failed" from "still in progress". Emit a
    # stable WAIT_TIMEOUT code with remediation that says poll, do NOT re-roll
    # (a re-roll double-bills MJ if the original lands).
    if result.get("timed_out") or status not in {"done", "failed"}:
        emit("CLI_ROLL_COMPLETED", asset_id=asset_id, dry_run=False, status="unknown")
        return {
            "ok": False,
            "asset_id": asset_id,
            "prompt": prompt,
            "job_id": job_id,
            "status": status,
            "outputs": outputs,
            "error": {
                "code": "WAIT_TIMEOUT",
                "message": (
                    f"job {job_id} did not reach a terminal state within {timeout}s "
                    f"(status={status!r}); Midjourney may still be rendering"
                ),
                "remediation": (
                    "Poll the job via GET /status/<job_id> or /wait/<job_id> on the bridge; "
                    "do NOT re-roll — the original may still complete and a re-roll bills MJ twice."
                ),
            },
        }

    emit("CLI_ROLL_COMPLETED", asset_id=asset_id, dry_run=False, status=status or "unknown")

    # status is "done" or "failed" here (the non-terminal / timed-out cases
    # returned above). On a real failure, mirror every other error path and the
    # module contract: a structured {code, message, remediation} envelope built
    # from the bridge's stable error_code — NOT the bare error string, which
    # drops the code a caller branches on.
    error_obj = None
    if status != "done":
        error_obj = {
            "code": result.get("error_code") or "JOB_FAILED",
            "message": result.get("error") or f"job {job_id} failed",
            "remediation": (
                "Inspect the failed job via GET /status/<job_id> on the bridge. "
                "If error_code is RESUBMIT_REQUIRED the in-flight job stalled or could "
                "not be confirmed across a restart — re-submit and verify rather than "
                "blindly retrying (a retry double-bills if the original landed); "
                "otherwise see RUNBOOK.md for the error_code's meaning."
            ),
        }

    return {
        "ok": status == "done",
        "asset_id": asset_id,
        "prompt": prompt,
        "job_id": job_id,
        "status": status,
        "outputs": outputs,
        "error": error_obj,
    }


def main() -> None:
    parser = argparse.ArgumentParser(prog="cascade-mj")
    parser.add_argument("asset_id", help="ID of the asset to roll, must exist in the registry")
    parser.add_argument(
        "--registry",
        required=True,
        type=Path,
        help="Path to the JSON registry file (asset_id -> prompt parts)",
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

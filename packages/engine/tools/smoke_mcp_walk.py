"""Live end-to-end smoke through the MCP tool surface.

Drives every cascade-mj-mcp tool an LLM operator would touch — not via Python
imports but via the real MCP stdio JSON-RPC transport. The bridge daemon and
the MCP server are both launched as subprocesses; the walk talks to the MCP
server the same way Claude Desktop, Cursor, or Cline would.

The tool sequence mirrors a normal agent loop::

    bridge_health -> compose_prompt -> imagine -> wait
                  -> crop_grid -> [alpha_key]? -> promote
                  -> log_append -> read_prompt_log

``alpha_key`` is opt-in: the agent (or this walk via ``--alpha-key``) decides
per-asset whether transparency is wanted. The default walk does crop ->
promote with no automatic keying, so a subject whose color matches the
background isn't silently destroyed.

Every call's envelope is printed for inspection. Each step that fails halts
the walk and propagates a non-zero exit code so this can be wired into CI
(against a separate sacrificial credentialed environment) or run by hand for
release-gate validation.

Requires a populated environment (see ``--env-file`` and RUNBOOK.md).

Usage::

    # Default: boot bridge, walk every tool, capture grid only (~30s)
    python3 tools/smoke_mcp_walk.py

    # Opt in to alpha-keying (flood-fill, default tolerance)
    python3 tools/smoke_mcp_walk.py --alpha-key

    # Threshold keyer with a wider tolerance
    python3 tools/smoke_mcp_walk.py --alpha-key --key-method threshold --key-tolerance 40

    # Exercise the parallel button-press path with all four upscales (~2-3m)
    python3 tools/smoke_mcp_walk.py --upscale all --wait-timeout 240

    # Use an already-running bridge
    python3 tools/smoke_mcp_walk.py --skip-bridge

    # Pick a specific subject / asset_id (default: random for re-runnability)
    python3 tools/smoke_mcp_walk.py --asset-id smoke_2026_06 --subject "a tiny rabbit"

Exit codes:
    0   every tool returned ok and the promoted artifact landed on disk
    1   any tool failed, bridge didn't ready, or the job didn't finish within
        --wait-timeout
    2   environment misconfiguration (missing .env, MCP package not importable)
"""
from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.util
import json
import os
import random
import secrets
import shutil
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

# --- silly-prompt rotation: kept here so the smoke fires with variety -------

_SUBJECTS = (
    "a tiny goofy salamander wearing sunglasses, holding a balloon",
    "a chubby cartoon frog blowing a bubblegum bubble",
    "a small confused owl wearing a graduation cap",
    "a sleepy hedgehog in a knitted scarf, looking suspicious",
    "a smug penguin holding a tiny coffee cup",
)

_CONSTRAINTS = ("side view", "flat illustration", "white background")


# --- IO plumbing -----------------------------------------------------------


class StepFailure(RuntimeError):
    """Raised when an MCP tool returns ``ok: false`` or the envelope is wrong."""


def _banner(name: str) -> None:
    print(f"\n=== {name} ===", flush=True)


def _print_envelope(name: str, envelope: dict, max_chars: int = 600) -> None:
    body = json.dumps(envelope, indent=2)
    print(f"[{name}] {body[:max_chars]}", flush=True)
    if len(body) > max_chars:
        print(f"  (truncated at {max_chars} of {len(body)} chars)", flush=True)


def _unwrap(name: str, result: Any) -> dict:
    """Convert an mcp CallToolResult into the tool's structured envelope."""
    content = getattr(result, "content", None)
    if not content:
        raise StepFailure(f"{name}: empty MCP content")
    first = content[0]
    text = getattr(first, "text", None)
    if text is None:
        raise StepFailure(f"{name}: MCP content is not text: {first!r}")
    try:
        envelope = json.loads(text)
    except json.JSONDecodeError as e:
        raise StepFailure(f"{name}: payload is not JSON: {text[:200]}") from e
    if not isinstance(envelope, dict) or "ok" not in envelope:
        raise StepFailure(f"{name}: envelope missing 'ok' field: {envelope!r}")
    if not envelope["ok"]:
        raise StepFailure(f"{name}: tool returned ok=false: {envelope.get('error')!r}")
    return envelope


# --- bridge subprocess management -----------------------------------------


def _bridge_health_url(bridge_url: str) -> str:
    return bridge_url.rstrip("/") + "/health"


def _wait_for_bridge(bridge_url: str, timeout_seconds: int) -> dict:
    """Poll GET /health until the bridge reports discord_ready=true.

    Returns the final health payload. Raises StepFailure on timeout.
    """
    url = _bridge_health_url(bridge_url)
    deadline = time.monotonic() + timeout_seconds
    last_error: str | None = None
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
            if payload.get("discord_ready") is True:
                return payload
            last_error = f"bridge up but discord_ready={payload.get('discord_ready')}"
        except (urllib.error.URLError, ConnectionError, OSError) as e:
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(0.5)
    raise StepFailure(
        f"bridge did not become ready within {timeout_seconds}s "
        f"(last status: {last_error})"
    )


def _spawn_bridge(log_path: Path) -> subprocess.Popen:
    """Spawn ``python3 -m cascade_img.backends.midjourney_discord.bridge``.

    Logs go to ``log_path``; the caller is responsible for terminating the
    process (use :func:`_terminate`).
    """
    fh = log_path.open("w", encoding="utf-8")
    return subprocess.Popen(
        [
            sys.executable,
            "-u",
            "-m",
            "cascade_img.backends.midjourney_discord.bridge",
        ],
        stdout=fh,
        stderr=subprocess.STDOUT,
        # detach into its own process group so a SIGINT to the smoke script
        # doesn't double-signal the bridge; we'll send SIGTERM explicitly.
        start_new_session=True,
    )


def _terminate(proc: subprocess.Popen, name: str, grace_seconds: float = 5.0) -> None:
    if proc.poll() is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
    except ProcessLookupError:
        return
    try:
        proc.wait(timeout=grace_seconds)
    except subprocess.TimeoutExpired:
        print(f"[{name}] grace exceeded, sending SIGKILL", flush=True)
        with contextlib.suppress(ProcessLookupError):
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)


# --- MCP walk --------------------------------------------------------------


@asynccontextmanager
async def _mcp_session(env: dict):
    """Open an MCP stdio client against cascade-mj-mcp.

    Prefers the installed ``cascade-mcp`` console script; falls back to
    ``python3 -m cascade_img.mcp_server`` for in-development installs where
    the entry point isn't on PATH.
    """
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    cmd = shutil.which("cascade-mcp")
    if cmd is None:
        server_args = ["-m", "cascade_img.mcp_server"]
        server = StdioServerParameters(command=sys.executable, args=server_args, env=env)
    else:
        server = StdioServerParameters(command=cmd, args=[], env=env)

    async with (
        stdio_client(server) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        yield session


async def _walk(args: argparse.Namespace, output_dir: Path) -> Path:
    """Run the tool sequence. Returns the promoted artifact's path on success."""
    asset_id = args.asset_id
    subject = args.subject or random.choice(_SUBJECTS)
    constraints = list(_CONSTRAINTS) if not args.no_constraints else []

    env = {**os.environ}
    # Tell cascade-mcp where the bridge and prompt log live.
    env["CASCADE_BRIDGE_URL"] = args.bridge_url
    env["CASCADE_PROMPT_LOG"] = str(output_dir / "cascade-prompt-log.jsonl")

    async with _mcp_session(env) as session:
        _banner("tools/list")
        tools = await session.list_tools()
        print(", ".join(t.name for t in tools.tools), flush=True)

        _banner("bridge_health")
        env_resp = _unwrap("bridge_health", await session.call_tool("bridge_health", {}))
        _print_envelope("bridge_health", env_resp)
        if not env_resp["result"].get("discord_ready"):
            raise StepFailure("bridge_health says discord_ready=false")

        _banner("compose_prompt")
        env_resp = _unwrap(
            "compose_prompt",
            await session.call_tool(
                "compose_prompt",
                {
                    "subject": subject,
                    "constraints": constraints,
                    "aspect_ratio": args.aspect_ratio,
                },
            ),
        )
        _print_envelope("compose_prompt", env_resp)
        prompt = env_resp["result"]["prompt"]

        _banner("imagine")
        env_resp = _unwrap(
            "imagine",
            await session.call_tool(
                "imagine",
                {"prompt": prompt, "asset_id": asset_id, "upscale": args.upscale},
            ),
        )
        _print_envelope("imagine", env_resp)
        job_id = env_resp["result"]["job_id"]

        _banner(f"wait (timeout={args.wait_timeout}s)")
        env_resp = _unwrap(
            "wait",
            await session.call_tool(
                "wait", {"job_id": job_id, "timeout": args.wait_timeout}
            ),
        )
        _print_envelope("wait", env_resp)
        job = env_resp["result"]
        if job["status"] != "done":
            raise StepFailure(
                f"job did not reach done: status={job['status']!r} "
                f"error_code={job.get('error_code')!r} error={job.get('error')!r}"
            )
        grid_path = job["grid_path"] or job["image_path"]
        if not grid_path or not Path(grid_path).exists():
            raise StepFailure(f"grid_path not on disk: {grid_path!r}")

        _banner(f"crop_grid (quadrant={args.quadrant})")
        cropped = output_dir / f"{asset_id}_u{args.quadrant}.png"
        env_resp = _unwrap(
            "crop_grid",
            await session.call_tool(
                "crop_grid",
                {"src": grid_path, "quadrant": args.quadrant, "dest": str(cropped)},
            ),
        )
        _print_envelope("crop_grid", env_resp)

        # alpha_key is opt-in. An LLM operator decides per-asset whether the
        # image needs transparency; the smoke walk does the same by default
        # (no auto-key) and only runs the step when --alpha-key is passed.
        promote_src = cropped
        if args.alpha_key:
            _banner(f"alpha_key (method={args.key_method}, tolerance={args.key_tolerance})")
            keyed = output_dir / f"{asset_id}_u{args.quadrant}_keyed.png"
            env_resp = _unwrap(
                "alpha_key",
                await session.call_tool(
                    "alpha_key",
                    {
                        "src": str(cropped),
                        "dest": str(keyed),
                        "tolerance": args.key_tolerance,
                        "method": args.key_method,
                    },
                ),
            )
            _print_envelope("alpha_key", env_resp)
            ratio = env_resp["result"].get("keyed_ratio")
            if ratio is not None:
                if ratio < 0.05:
                    print(
                        f"  warning: keyed_ratio={ratio} — keyer found "
                        "almost no background; consider raising tolerance "
                        "or skipping alpha-key for this asset",
                        flush=True,
                    )
                elif ratio > 0.92:
                    print(
                        f"  warning: keyed_ratio={ratio} — keyer ate most "
                        "of the frame; subject likely matched background "
                        "(reroll with higher contrast or skip alpha-key)",
                        flush=True,
                    )
            promote_src = keyed
        else:
            print(
                "  (alpha_key not requested; pass --alpha-key to opt in)",
                flush=True,
            )

        _banner("promote")
        promoted_dir = output_dir / "promoted"
        promoted_dir.mkdir(parents=True, exist_ok=True)
        promoted = promoted_dir / f"{asset_id}.png"
        env_resp = _unwrap(
            "promote",
            await session.call_tool(
                "promote", {"src": str(promote_src), "dest": str(promoted)}
            ),
        )
        _print_envelope("promote", env_resp)

        _banner("log_append")
        env_resp = _unwrap(
            "log_append",
            await session.call_tool(
                "log_append",
                {
                    "asset_id": asset_id,
                    "prompt": prompt,
                    "backend": "midjourney_discord",
                    "job_id": job_id,
                    "outputs": {"promoted": str(promoted)},
                    "agent_decision": "promote",
                    "agent_reason": (
                        "smoke walk; quadrant 3 promoted via alpha-keyed crop"
                    ),
                },
            ),
        )
        _print_envelope("log_append", env_resp)

        _banner("read_prompt_log (n=3)")
        env_resp = _unwrap(
            "read_prompt_log", await session.call_tool("read_prompt_log", {"n": 3})
        )
        _print_envelope("read_prompt_log", env_resp)
        records = env_resp["result"]["records"]
        # Roundtrip check: the last record we wrote must come back.
        if not records or records[-1]["asset_id"] != asset_id:
            raise StepFailure(
                f"log roundtrip mismatch: last record asset_id="
                f"{records[-1].get('asset_id') if records else None!r} "
                f"expected {asset_id!r}"
            )

    if not promoted.exists():
        raise StepFailure(f"promoted artifact missing: {promoted}")
    return promoted


# --- top-level orchestration ----------------------------------------------


def _ensure_env(env_file: Path | None) -> None:
    """Load env_file if given; verify dotenv saw the required vars."""
    if env_file is not None:
        if not env_file.exists():
            raise StepFailure(f"--env-file does not exist: {env_file}")
        # Lightweight .env parser: KEY=VALUE per line, # comments, no quotes.
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())
    required = ("DISCORD_USER_TOKEN", "MJ_CHANNEL_ID", "MJ_IMAGINE_VERSION")
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        raise StepFailure(
            f"missing required env vars: {', '.join(missing)} "
            f"(pass --env-file or export them)"
        )


def _ensure_package_importable() -> None:
    if importlib.util.find_spec("cascade_img") is None:
        print(
            "cascade_img not installed in this Python — "
            "run `pip install -e packages/engine` first.",
            file=sys.stderr,
        )
        sys.exit(2)


def _make_default_asset_id() -> str:
    return f"smoke_{int(time.time())}_{secrets.token_hex(3)}"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="smoke_mcp_walk",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=None,
        help="Path to a .env file (KEY=VALUE per line). Loaded into os.environ.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./smoke-output").resolve(),
        help="Where the bridge writes its artifacts (also exported as MJ_OUTPUT_DIR).",
    )
    parser.add_argument(
        "--bridge-url",
        default="http://127.0.0.1:5000",
        help="Bridge URL the MCP server will hit.",
    )
    parser.add_argument(
        "--skip-bridge",
        action="store_true",
        help="Don't spawn the bridge — assume one is already running at --bridge-url.",
    )
    parser.add_argument(
        "--asset-id",
        default=None,
        help="Asset ID for this run. Defaults to smoke_<ts>_<rand> for re-runnability.",
    )
    parser.add_argument(
        "--subject",
        default=None,
        help="Prompt subject. Defaults to a random pick from a built-in rotation.",
    )
    parser.add_argument(
        "--no-constraints",
        action="store_true",
        help="Drop the default constraints (side view / flat / white bg).",
    )
    parser.add_argument(
        "--aspect-ratio",
        default="1:1",
        help="MJ aspect ratio (default 1:1).",
    )
    parser.add_argument(
        "--upscale",
        default=None,
        help="None (grid only), '1'-'4' (single slot), or 'all' (every slot).",
    )
    parser.add_argument(
        "--quadrant",
        type=int,
        choices=(0, 1, 2, 3, 4),
        default=3,
        help="Quadrant to crop from the grid: 1=TL, 2=TR, 3=BL (default), 4=BR. "
        "0 returns the whole image (single-upscale passthrough).",
    )
    parser.add_argument(
        "--alpha-key",
        action="store_true",
        help="Opt in to the alpha-key step. Off by default — the operator "
        "decides per asset whether transparency is wanted.",
    )
    parser.add_argument(
        "--key-method",
        choices=("flood", "threshold"),
        default="flood",
        help="alpha_key algorithm: flood (default; corner-anchored flood-fill) "
        "or threshold (per-pixel distance from corner-average).",
    )
    parser.add_argument(
        "--key-tolerance",
        type=int,
        default=24,
        help="alpha_key per-channel tolerance band (0-255).",
    )
    parser.add_argument(
        "--wait-timeout",
        type=int,
        default=120,
        help="Seconds to wait for the job to reach done/failed.",
    )
    parser.add_argument(
        "--bridge-boot-timeout",
        type=int,
        default=30,
        help="Seconds to wait for the bridge to report discord_ready=true.",
    )
    parser.add_argument(
        "--keep-bridge-log",
        action="store_true",
        help="Leave the bridge log on disk after the walk.",
    )
    args = parser.parse_args(argv)

    _ensure_package_importable()
    if not args.skip_bridge:
        try:
            _ensure_env(args.env_file)
        except StepFailure as e:
            print(f"FAIL: {e}", file=sys.stderr)
            return 2

    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    os.environ["MJ_OUTPUT_DIR"] = str(output_dir)

    if args.asset_id is None:
        args.asset_id = _make_default_asset_id()

    bridge_log = output_dir / "smoke-bridge.log"
    bridge_proc: subprocess.Popen | None = None

    t_start = time.monotonic()
    try:
        if not args.skip_bridge:
            _banner("spawn bridge")
            bridge_proc = _spawn_bridge(bridge_log)
            print(f"bridge PID={bridge_proc.pid} log={bridge_log}", flush=True)
        else:
            _banner("using already-running bridge")

        health = _wait_for_bridge(args.bridge_url, args.bridge_boot_timeout)
        _print_envelope("health", health)

        promoted = asyncio.run(_walk(args, output_dir))
    except StepFailure as e:
        print(f"\nFAIL: {e}", file=sys.stderr)
        if bridge_proc is not None and bridge_log.exists():
            print(f"\n--- last 30 lines of {bridge_log} ---", file=sys.stderr)
            for line in bridge_log.read_text(encoding="utf-8").splitlines()[-30:]:
                print(line, file=sys.stderr)
        return 1
    except Exception as e:
        print(f"\nFAIL (unhandled): {type(e).__name__}: {e}", file=sys.stderr)
        return 1
    finally:
        if bridge_proc is not None:
            _terminate(bridge_proc, "bridge")
        if not args.keep_bridge_log and bridge_log.exists():
            # Bridge logs can be inspected via --keep-bridge-log on failure;
            # default cleanup keeps the output dir tidy across re-runs.
            with contextlib.suppress(OSError):
                bridge_log.unlink()

    elapsed = time.monotonic() - t_start
    _banner("PASS")
    print(f"promoted artifact: {promoted}", flush=True)
    print(f"prompt log:        {output_dir / 'cascade-prompt-log.jsonl'}", flush=True)
    print(f"asset_id:          {args.asset_id}", flush=True)
    print(f"elapsed:           {elapsed:.1f}s", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

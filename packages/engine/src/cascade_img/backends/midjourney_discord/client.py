"""
Tiny CLI client for the bridge. Use this to smoke-test, or import the
`imagine()` function from Python.

CLI:
    python mj_client.py --asset relic_chip_v01 \
        "a glowing turquoise glass chip, jewel-tone, deep gem facets, \
         centered on transparent background, neo-retro treasure UI icon, \
         soft inner glow, late-90s online puzzle game vibe with 2026 polish \
         --ar 1:1 --v 7 --style raw"

    # then watch it land in ./generated/relic_chip_v01.png

Returns exit 0 on success, prints the saved path. Non-zero on failure.
"""

import argparse
import json
import sys
import time

import requests

DEFAULT_BASE = "http://127.0.0.1:5000"


def imagine(
    prompt: str,
    asset_id: str,
    base: str = DEFAULT_BASE,
    timeout_s: int = 240,
    upscale=None,
) -> dict:
    """Fire one /imagine, block until done or failed.

    upscale: None (grid only), 1..4 (single upscale, becomes <asset_id>.png),
             or "all" (four files <asset_id>_u1..u4.png).
    """
    body = {"prompt": prompt, "asset_id": asset_id}
    if upscale is not None:
        body["upscale"] = upscale
    r = requests.post(f"{base}/imagine", json=body, timeout=30)
    r.raise_for_status()
    job_id = r.json()["job_id"]

    # Long-poll in chunks so we can stream progress to stdout
    deadline = time.time() + timeout_s
    last_progress = ""
    while time.time() < deadline:
        chunk = min(20, int(deadline - time.time()))
        if chunk <= 0:
            break
        r = requests.get(f"{base}/wait/{job_id}", params={"timeout": chunk}, timeout=chunk + 5)
        data = r.json()
        if data.get("progress") and data["progress"] != last_progress:
            print(f"  [{asset_id}] {data['status']} {data['progress']}", file=sys.stderr)
            last_progress = data["progress"]
        if data.get("status") in ("done", "failed"):
            return data
    return {"status": "client_timeout", "job_id": job_id}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("prompt", help="The full Midjourney prompt, flags included.")
    p.add_argument("--asset", required=True, help="Output filename stem, e.g. relic_chip_v01")
    p.add_argument(
        "--upscale",
        default=None,
        help="None (default, grid only), 1-4 (single upscale), or 'all' (four files).",
    )
    p.add_argument("--base", default=DEFAULT_BASE)
    p.add_argument("--timeout", type=int, default=240)
    args = p.parse_args()

    result = imagine(args.prompt, args.asset, args.base, args.timeout, args.upscale)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result.get("status") == "done" else 1)


if __name__ == "__main__":
    main()

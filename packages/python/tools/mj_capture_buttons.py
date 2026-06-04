"""Live capture of Midjourney's response-message button surface.

Fires one /imagine, waits for the grid, presses U1, waits for the upscaled
image, and dumps every message component (label, custom_id, emoji, style) MJ
attaches. That is the real action surface — Vary / Zoom / Pan / Make Square /
Animate / favorite — for THIS account's MJ version. The endpoints and
result matchers are written against this capture, not guessed: reverse-engineer
the external surface before authoring against it.

    python3 tools/mj_capture_buttons.py --env-file /path/to/.env

Prints a JSON catalog to stdout: {"grid": [...buttons...], "upscaled": [...]}.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import uuid
from pathlib import Path

import discord  # discord.py-self
import requests

from cascade_img.backends.midjourney_discord.bridge import (
    MJ_BOT_ID,
    Config,
)

_INTERACTION_APP_CMD = 2
_INTERACTION_MSG_COMPONENT = 3
_COMPONENT_BUTTON = 2
_OPTION_STRING = 3
_UPSAMPLE_BTN = "MJ::JOB::upsample::1::"  # U1 prefix; uuid appended at runtime


def _dump_components(message) -> list[dict]:
    out: list[dict] = []
    for row in message.components or []:
        for c in getattr(row, "children", []) or []:
            emoji = getattr(c, "emoji", None)
            out.append(
                {
                    "label": getattr(c, "label", None) or None,
                    "custom_id": getattr(c, "custom_id", None),
                    "emoji": str(emoji) if emoji else None,
                    "style": getattr(getattr(c, "style", None), "name", None),
                    "url": getattr(c, "url", None),
                }
            )
    return out


def _extract_uuid(message) -> str | None:
    for row in message.components or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            if cid.startswith("MJ::JOB::upsample::"):
                return cid.rsplit("::", 1)[-1]
    return None


async def _post(cfg: Config, client, payload: dict) -> requests.Response:
    payload["application_id"] = str(MJ_BOT_ID)
    payload["channel_id"] = str(cfg.channel_id)
    payload["session_id"] = client.ws.session_id
    if cfg.guild_id:
        payload["guild_id"] = cfg.guild_id
    headers = {"Authorization": cfg.discord_token, "Content-Type": "application/json"}
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(
        None,
        lambda: requests.post(
            "https://discord.com/api/v9/interactions", json=payload, headers=headers, timeout=30
        ),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mj_capture_buttons")
    parser.add_argument("--env-file", type=Path, default=None)
    parser.add_argument("--timeout", type=int, default=180)
    args = parser.parse_args(argv)

    if args.env_file and args.env_file.exists():
        for line in args.env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip())

    cfg = Config.from_env()
    token = uuid.uuid4().hex[:8]
    needle = f"cscidnocollide{token}"
    prompt = f"a plain grey circle on white, flat icon --ar 1:1 --v 7 --no {needle}"

    client = discord.Client()
    catalog: dict[str, list[dict]] = {}
    state = {"grid_msg_id": None, "pressed": False}
    done = asyncio.Event()

    @client.event
    async def on_ready():
        print(f"connected as {client.user}; firing /imagine", file=sys.stderr, flush=True)
        await _post(
            cfg,
            client,
            {
                "type": _INTERACTION_APP_CMD,
                "data": {
                    "version": cfg.mj_imagine_version,
                    "id": cfg.mj_imagine_command_id,
                    "name": "imagine",
                    "type": 1,
                    "options": [{"type": _OPTION_STRING, "name": "prompt", "value": prompt}],
                    "application_command": {
                        "id": cfg.mj_imagine_command_id,
                        "application_id": str(MJ_BOT_ID),
                        "version": cfg.mj_imagine_version,
                        "name": "imagine",
                        "type": 1,
                        "options": [
                            {
                                "type": _OPTION_STRING,
                                "name": "prompt",
                                "description": "The prompt to imagine",
                            }
                        ],
                    },
                },
            },
        )

    async def _handle(message):
        if message.author.id != MJ_BOT_ID or message.channel.id != cfg.channel_id:
            return
        content = message.content or ""
        if needle not in content:
            return
        comps = _dump_components(message)
        # Grid: has upsample buttons and is not an "Image #" upscale result.
        if (
            not state["pressed"]
            and "Image #" not in content
            and any((b["custom_id"] or "").startswith("MJ::JOB::upsample::") for b in comps)
        ):
            catalog["grid"] = comps
            uid = _extract_uuid(message)
            if uid:
                state["pressed"] = True
                state["grid_msg_id"] = message.id
                print(
                    f"grid captured ({len(comps)} buttons); pressing U1",
                    file=sys.stderr,
                    flush=True,
                )
                await _post(
                    cfg,
                    client,
                    {
                        "type": _INTERACTION_MSG_COMPONENT,
                        "message_id": str(message.id),
                        "data": {
                            "component_type": _COMPONENT_BUTTON,
                            "custom_id": _UPSAMPLE_BTN + uid,
                        },
                    },
                )
        elif "Image #" in content and message.attachments:
            catalog["upscaled"] = comps
            print(f"upscaled image captured ({len(comps)} buttons)", file=sys.stderr, flush=True)
            done.set()

    @client.event
    async def on_message(message):
        await _handle(message)

    @client.event
    async def on_message_edit(_before, after):
        await _handle(after)

    async def runner():
        task = asyncio.create_task(client.start(cfg.discord_token))
        try:
            await asyncio.wait_for(done.wait(), timeout=args.timeout)
        except TimeoutError:
            print(f"timed out after {args.timeout}s", file=sys.stderr, flush=True)
        finally:
            await client.close()
            task.cancel()

    asyncio.run(runner())
    print(json.dumps(catalog, indent=2))
    return 0 if catalog.get("upscaled") else 1


if __name__ == "__main__":
    sys.exit(main())

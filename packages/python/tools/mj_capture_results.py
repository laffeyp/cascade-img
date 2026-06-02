"""Live capture of how Midjourney ECHOES derived-action results (Wave F receive side).

Submit-side custom_ids are already mapped (mj_capture_buttons.py). This maps the
receive side — the only remaining unknown before the Wave F result matchers can
be written:

    /imagine -> grid -> press U1 -> upscaled image
             -> press Vary (Strong)  -> capture the result message
             -> press Animate (High) -> capture the result message

For each result it records: message content, whether it re-echoes the parent
prompt token, the attachment filename/extension (PNG/WEBP grid vs MP4 video),
and a new job uuid (if a new grid). Presses are spaced by real render time
(~30-60s each), so this runs at human speed.

    python3 tools/mj_capture_results.py --env-file /path/to/.env
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

from cascade_img.backends.midjourney_discord.bridge import MJ_BOT_ID, Config

_APP_CMD = 2
_MSG_COMPONENT = 3
_BUTTON = 2
_OPT_STRING = 3


def _uuid_in(message) -> str | None:
    for row in message.components or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            if cid.startswith("MJ::JOB::upsample"):
                # ...::slot::{uuid}::SOLO  or  ...::slot::{uuid}
                parts = cid.split("::")
                for p in parts:
                    if len(p) == 36 and p.count("-") == 4:
                        return p
    return None


def _attachment_info(message) -> dict | None:
    if not message.attachments:
        return None
    a = message.attachments[0]
    name = a.filename or ""
    return {
        "filename": name,
        "ext": os.path.splitext(name)[1].lower(),
        "content_type": getattr(a, "content_type", None),
        "size": getattr(a, "size", None),
    }


def _has_upsample(message) -> bool:
    for row in message.components or []:
        for c in getattr(row, "children", []) or []:
            if (getattr(c, "custom_id", "") or "").startswith("MJ::JOB::upsample"):
                return True
    return False


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mj_capture_results")
    ap.add_argument("--env-file", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=360)
    args = ap.parse_args(argv)

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
    out: dict = {"needle": needle}
    seen_uuids: set[str] = set()
    st = {"phase": "grid", "upscale_uuid": None, "upscale_msg": None}
    done = asyncio.Event()

    async def _post(payload: dict) -> None:
        payload["application_id"] = str(MJ_BOT_ID)
        payload["channel_id"] = str(cfg.channel_id)
        payload["session_id"] = client.ws.session_id
        if cfg.guild_id:
            payload["guild_id"] = cfg.guild_id
        headers = {"Authorization": cfg.discord_token, "Content-Type": "application/json"}
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: requests.post(
                "https://discord.com/api/v9/interactions", json=payload, headers=headers, timeout=30
            ),
        )

    async def _press(message_id: int, custom_id: str) -> None:
        await _post(
            {
                "type": _MSG_COMPONENT,
                "message_id": str(message_id),
                "data": {"component_type": _BUTTON, "custom_id": custom_id},
            }
        )

    @client.event
    async def on_ready():
        print(f"connected as {client.user}; firing /imagine", file=sys.stderr, flush=True)
        await _post(
            {
                "type": _APP_CMD,
                "data": {
                    "version": cfg.mj_imagine_version,
                    "id": cfg.mj_imagine_command_id,
                    "name": "imagine",
                    "type": 1,
                    "options": [{"type": _OPT_STRING, "name": "prompt", "value": prompt}],
                    "application_command": {
                        "id": cfg.mj_imagine_command_id,
                        "application_id": str(MJ_BOT_ID),
                        "version": cfg.mj_imagine_version,
                        "name": "imagine",
                        "type": 1,
                        "options": [
                            {
                                "type": _OPT_STRING,
                                "name": "prompt",
                                "description": "The prompt to imagine",
                            }
                        ],
                    },
                },
            }
        )

    async def _handle(message):
        if message.author.id != MJ_BOT_ID or message.channel.id != cfg.channel_id:
            return
        content = message.content or ""
        if needle not in content:
            return
        is_image = "Image #" in content
        uid = _uuid_in(message)

        if st["phase"] == "grid" and _has_upsample(message) and not is_image:
            if uid:
                seen_uuids.add(uid)
                st["phase"] = "upscale"
                print("grid -> press U1", file=sys.stderr, flush=True)
                await _press(message.id, f"MJ::JOB::upsample::1::{uid}")
        elif st["phase"] == "upscale" and is_image and message.attachments:
            st["upscale_uuid"] = uid
            st["upscale_msg"] = message.id
            seen_uuids.add(uid)
            st["phase"] = "vary"
            print("upscaled -> press Vary (Strong)", file=sys.stderr, flush=True)
            await _press(message.id, f"MJ::JOB::high_variation::1::{uid}::SOLO")
        elif (
            st["phase"] == "vary"
            and _has_upsample(message)
            and not is_image
            and uid not in seen_uuids
        ):
            out["vary_strong_result"] = {
                "content": content[:300],
                "echoes_parent_token": needle in content,
                "new_uuid": uid,
                "is_new_grid": True,
                "attachment": _attachment_info(message),
            }
            print("vary result captured -> press Animate (High)", file=sys.stderr, flush=True)
            st["phase"] = "animate"
            await _press(st["upscale_msg"], f"MJ::JOB::animate_high::1::{st['upscale_uuid']}::SOLO")
        elif st["phase"] == "animate" and message.attachments and message.id != st["upscale_msg"]:
            info = _attachment_info(message)
            if info and info["ext"] not in (".png", ".webp"):
                out["animate_high_result"] = {"content": content[:300], "attachment": info}
                print(f"animate result captured: {info['filename']}", file=sys.stderr, flush=True)
                done.set()

    @client.event
    async def on_message(message):
        await _handle(message)

    @client.event
    async def on_message_edit(_b, after):
        await _handle(after)

    async def runner():
        task = asyncio.create_task(client.start(cfg.discord_token))
        try:
            await asyncio.wait_for(done.wait(), timeout=args.timeout)
        except TimeoutError:
            print(
                f"timed out after {args.timeout}s (partial capture below)",
                file=sys.stderr,
                flush=True,
            )
        finally:
            await client.close()
            task.cancel()

    asyncio.run(runner())
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

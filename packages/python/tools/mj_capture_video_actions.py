"""Live probe of the Midjourney native-video RESULT button surface (V-3).

V-2 captured the native video result (a webp grid with `video_virtual_upscale`
+ `reroll` buttons). This probes what those buttons DO: fire a native video,
wait for the grid result, press `video_virtual_upscale::1`, and log the SOLO
video that comes back + its buttons (the Extend High/Low surface) — so V-3's
mj_action-for-video is built to the observed custom_ids/routing, not guessed.

    python3 tools/mj_capture_video_actions.py --env-file /path/to/.env
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
import uuid
from pathlib import Path

import discord  # discord.py-self
import requests

from cascade_img.backends.midjourney_discord.bridge import MJ_BOT_ID, Config

_APP_CMD = 2
_MSG_COMPONENT = 3
_BUTTON = 2
_OPT_STRING = 3
_VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v", ".webp")


def _has_upsample(message) -> bool:
    return any(
        (getattr(c, "custom_id", "") or "").startswith("MJ::JOB::upsample")
        for row in (message.components or [])
        for c in (getattr(row, "children", []) or [])
    )


def _buttons(message) -> list[str]:
    return [
        (getattr(c, "custom_id", "") or getattr(c, "label", "") or "")
        for row in (message.components or [])
        for c in (getattr(row, "children", []) or [])
    ]


def _uuid_from(prefix: str, message) -> str | None:
    for cid in _buttons(message):
        if cid.startswith(prefix):
            for p in cid.split("::"):
                if len(p) == 36 and p.count("-") == 4:
                    return p
    return None


def _atts(message) -> list[dict]:
    out = []
    for a in message.attachments or []:
        name = a.filename or ""
        out.append(
            {
                "filename": name,
                "ext": os.path.splitext(name)[1].lower(),
                "content_type": getattr(a, "content_type", None),
                "size": getattr(a, "size", None),
            }
        )
    return out


def _is_video(att: dict) -> bool:
    return att["ext"] in _VIDEO_EXT or (att.get("content_type") or "").startswith("video/")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mj_capture_video_actions")
    ap.add_argument("--env-file", type=Path, default=None)
    ap.add_argument("--timeout", type=int, default=700)
    ap.add_argument(
        "--slot",
        type=int,
        default=1,
        help="which video_virtual_upscale::N slot to press (probe whether the "
        "resulting SOLO's animate_*_extend button is grid-aligned ::N or SOLO-local ::1)",
    )
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
    seed_prompt = f"a plain grey circle on white, flat icon --ar 1:1 --no {needle}"

    client = discord.Client()
    out: dict = {"action_trail": []}
    st = {"phase": "grid", "pressed_at": None}
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

    async def _imagine(prompt: str) -> None:
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
                        "options": [{"type": _OPT_STRING, "name": "prompt", "description": "p"}],
                    },
                },
            }
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
        print("connected; firing seed /imagine", file=sys.stderr, flush=True)
        await _imagine(seed_prompt)

    async def _handle(message):
        if message.author.id != MJ_BOT_ID or message.channel.id != cfg.channel_id:
            return
        content = message.content or ""

        if st["phase"] in ("grid", "upscale") and needle not in content:
            return
        if st["phase"] == "grid" and _has_upsample(message) and "Image #" not in content:
            uid = _uuid_from("MJ::JOB::upsample", message)
            if uid:
                st["phase"] = "upscale"
                await _press(message.id, f"MJ::JOB::upsample::1::{uid}")
            return
        if st["phase"] == "upscale" and "Image #" in content and message.attachments:
            st["phase"] = "videowait"
            await _imagine(f"{message.attachments[0].url} --video --loop")
            print("fired native video; waiting for the grid result", file=sys.stderr, flush=True)
            return

        # Wait for the video GRID result (a video attachment + video_virtual_upscale buttons).
        if st["phase"] == "videowait":
            uid = _uuid_from("MJ::JOB::video_virtual_upscale", message)
            if uid and any(_is_video(a) for a in _atts(message)):
                out["grid_buttons"] = _buttons(message)
                out["pressed_slot"] = args.slot
                st["phase"] = "action"
                st["pressed_at"] = time.monotonic()
                print(
                    f"video grid landed; buttons={_buttons(message)}; "
                    f"pressing video_virtual_upscale::{args.slot}",
                    file=sys.stderr,
                    flush=True,
                )
                await _press(message.id, f"MJ::JOB::video_virtual_upscale::{args.slot}::{uid}")
            return

        # Log everything after the press: the SOLO video + its Extend buttons.
        if st["phase"] == "action":
            entry = {
                "content": content[:200],
                "attachments": _atts(message),
                "buttons": _buttons(message)[:14],
                "t": round(time.monotonic() - st["pressed_at"], 1),
            }
            out["action_trail"].append(entry)
            print(
                f"  [{entry['t']}s] atts={[a['filename'] for a in entry['attachments']]} "
                f"buttons={entry['buttons']}",
                file=sys.stderr,
                flush=True,
            )
            # Finish once a SOLO video lands carrying NEW (extend) buttons.
            if any(_is_video(a) for a in entry["attachments"]) and entry["buttons"]:
                out["solo_video"] = entry
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
            print("timed out (partial trail below)", file=sys.stderr, flush=True)
        finally:
            await client.close()
            task.cancel()

    asyncio.run(runner())
    print(json.dumps(out, indent=2))
    return 0 if out.get("solo_video") else 1


if __name__ == "__main__":
    sys.exit(main())

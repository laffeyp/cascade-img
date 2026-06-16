"""Live probe of the Midjourney NATIVE video (`--video`) result shape.

Distinct from mj_capture_animate.py (which presses the Animate button on a SOLO
upscale). This probes the path V-2 must build: fire ``/imagine`` with a starting
image URL + ``--video --loop`` and capture EXACTLY how MJ returns native video —
how many clips, in one message or several, the attachment types, and the buttons
on the result. The receiver (match + download the video batch) has to be built to
this shape, so we observe it rather than guess (the --sd / --stop external-grammar
discipline, edge case).

Flow: /imagine an icon -> grid -> press U1 -> grab the upscaled image's CDN URL ->
/imagine ``<url> --video --loop`` -> log every MJ message until a video lands (or
timeout), then dump the full trail.

    python3 tools/mj_capture_video.py --env-file /path/to/.env
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
_VIDEO_EXT = (".mp4", ".mov", ".webm", ".m4v")


def _uuid_in(message) -> str | None:
    for row in message.components or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            if cid.startswith("MJ::JOB::upsample"):
                for p in cid.split("::"):
                    if len(p) == 36 and p.count("-") == 4:
                        return p
    return None


def _has_upsample(message) -> bool:
    return any(
        (getattr(c, "custom_id", "") or "").startswith("MJ::JOB::upsample")
        for row in (message.components or [])
        for c in (getattr(row, "children", []) or [])
    )


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
                "url": getattr(a, "url", None),
            }
        )
    return out


def _buttons(message) -> list[str]:
    return [
        (getattr(c, "custom_id", "") or getattr(c, "label", "") or "")
        for row in (message.components or [])
        for c in (getattr(row, "children", []) or [])
    ]


def _is_video(att: dict) -> bool:
    return att["ext"] in _VIDEO_EXT or (att.get("content_type") or "").startswith("video/")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mj_capture_video")
    ap.add_argument("--env-file", type=Path, default=None)
    ap.add_argument("--video-timeout", type=int, default=600)
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
    # Plain icon to get a clean starting frame; default model (V8.1).
    seed_prompt = f"a plain grey circle on white, flat icon --ar 1:1 --no {needle}"

    client = discord.Client()
    out: dict = {"needle": needle, "video_prompt": None, "video_trail": []}
    st = {"phase": "grid", "video_fired_at": None, "start_url": None}
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
        print(f"connected as {client.user}; firing seed /imagine", file=sys.stderr, flush=True)
        await _imagine(seed_prompt)

    async def _handle(message):
        if message.author.id != MJ_BOT_ID or message.channel.id != cfg.channel_id:
            return
        content = message.content or ""

        if st["phase"] in ("grid", "upscale") and needle not in content:
            return
        if st["phase"] == "grid" and _has_upsample(message) and "Image #" not in content:
            uid = _uuid_in(message)
            if uid:
                st["phase"] = "upscale"
                print("grid -> press U1", file=sys.stderr, flush=True)
                await _press(message.id, f"MJ::JOB::upsample::1::{uid}")
            return
        if st["phase"] == "upscale" and "Image #" in content and message.attachments:
            start_url = message.attachments[0].url
            st["start_url"] = start_url
            video_prompt = f"{start_url} --video --loop"
            out["video_prompt"] = video_prompt
            st["phase"] = "video"
            st["video_fired_at"] = time.monotonic()
            print(
                f"upscaled -> fire native video: {video_prompt[:80]}…; logging ALL MJ messages now",
                file=sys.stderr,
                flush=True,
            )
            await _imagine(video_prompt)
            return

        if st["phase"] == "video":
            atts = _atts(message)
            entry = {
                "content": content[:240],
                "attachments": atts,
                "buttons": _buttons(message)[:12],
                "n_components": sum(
                    len(getattr(r, "children", []) or []) for r in (message.components or [])
                ),
                "t_since_fire": round(time.monotonic() - st["video_fired_at"], 1),
            }
            out["video_trail"].append(entry)
            print(
                f"  [{entry['t_since_fire']}s] {content[:70]!r} "
                f"atts={[(a['filename'], a['content_type']) for a in atts]}",
                file=sys.stderr,
                flush=True,
            )
            if any(_is_video(a) for a in atts):
                out["first_video"] = entry
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
            await asyncio.wait_for(done.wait(), timeout=args.video_timeout + 180)
        except TimeoutError:
            print("timed out (partial trail below)", file=sys.stderr, flush=True)
        finally:
            await client.close()
            task.cancel()

    asyncio.run(runner())
    print(json.dumps(out, indent=2))
    return 0 if out.get("first_video") else 1


if __name__ == "__main__":
    sys.exit(main())

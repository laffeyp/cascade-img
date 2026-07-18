"""Bounded in-memory buffer of recent MJ-bot channel messages.

The gateway handler already sees every message in the watched channel; this
module keeps the last N as structured records so ``GET /channel/recent`` can
answer "what happened in the channel?" — including results a human produced by
hand in Discord, which the job matchers have no tracked job for. Read-only
observation: nothing here mutates job state.

Records are extracted once at ingest time (the ``discord.Message`` is not
retained — it belongs to discord.py-self's cache) and served verbatim by the
catch-up route, which adds the job-table resolution (``tracked_job_id``) at
read time so it reflects the current table, not the table at arrival time.

Binding discipline: ``CHANNEL_BUFFER`` is a deque mutated in place and never
rebound, so importing it by name is safe. All access goes through
``record_message`` / ``recent_records`` which serialize on ``_BUFFER_LOCK``.
"""

from __future__ import annotations

import re
import threading
from collections import deque
from typing import Any

from cascade_img.backends.midjourney_discord.transport.discord_parse import (
    _ACTION_MARKERS,
    _has_result_button,
)

# 200 messages ≈ hours of a busy dedicated channel; bounded so the daemon's
# memory does not grow with uptime. Cold start (daemon restarted after the
# human acted) is served by the route's REST history fallback, not the buffer.
_BUFFER_MAXLEN = 200

CHANNEL_BUFFER: deque[dict[str, Any]] = deque(maxlen=_BUFFER_MAXLEN)
_BUFFER_LOCK = threading.Lock()

_TOKEN_RE = re.compile(r"cscidnocollide([0-9a-f]{8})")
_IMAGE_TAG_RE = re.compile(r"Image #(\d+)")


def _classify_kind(content: str, attachments: list[dict[str, Any]]) -> str:
    """Classify an MJ-bot message by what its artifact is.

    - ``solo``  — a single extracted image ("Image #N" label; a U-press result).
    - ``video`` — a native-video result (``--video`` prompt echo, or a video
      attachment: a video_upscale/extend mp4, or the animated-webp final).
    - ``grid``  — an attachment-bearing result that is neither (the 2x2 grid).
    - ``other`` — no attachment (moderation notices, acks, progress stubs).
    """
    if not attachments:
        return "other"
    att = attachments[0]
    ct = (att.get("content_type") or "").lower()
    name = (att.get("filename") or "").lower()
    if "--video" in content or ct.startswith("video/") or name.endswith((".mp4", ".mov", ".webm")):
        return "video"
    if _IMAGE_TAG_RE.search(content):
        return "solo"
    return "grid"


def _available_actions(message) -> list[str]:
    """The ``mj_action`` names whose buttons are present on ``message`` —
    the same marker match ``_find_action_custom_id`` presses by, so this list
    is exactly what an adoption of this message would unlock."""
    cids: list[str] = []
    for row in getattr(message, "components", None) or []:
        for c in getattr(row, "children", None) or []:
            cid = getattr(c, "custom_id", "") or ""
            if cid:
                cids.append(cid)
    out = []
    for action, marker in _ACTION_MARKERS.items():
        if action == "video_upscale":
            # Slot lives in the custom_id (video_virtual_upscale::N); presence of
            # any slot counts.
            if any(marker in cid for cid in cids):
                out.append(action)
        elif any(marker in cid for cid in cids):
            out.append(action)
    return out


def message_record(message, event: str = "message") -> dict[str, Any]:
    """Extract the structured catch-up record from a ``discord.Message``.

    Structure-only, like the raw-capture hook — no job-table reads here (the
    route resolves ``tracked_job_id`` at read time)."""
    content = message.content or ""
    attachments: list[dict[str, Any]] = []
    for a in getattr(message, "attachments", None) or []:
        attachments.append(
            {
                "filename": getattr(a, "filename", None),
                "url": getattr(a, "url", None),
                "content_type": getattr(a, "content_type", None),
                "width": getattr(a, "width", None),
                "height": getattr(a, "height", None),
            }
        )
    token_m = _TOKEN_RE.search(content)
    slot_m = _IMAGE_TAG_RE.search(content)
    created_at = getattr(message, "created_at", None)
    return {
        "message_id": str(getattr(message, "id", "")),
        "event": event,
        "kind": _classify_kind(content, attachments),
        "prompt_text": content,
        "routing_token": token_m.group(1) if token_m else None,
        "slot_label": f"Image #{slot_m.group(1)}" if slot_m else None,
        "attachment": attachments[0] if attachments else None,
        "buttons": _available_actions(message),
        "has_result_button": _has_result_button(message),
        "created_at": created_at.isoformat() if created_at is not None else None,
    }


def record_message(message, event: str = "message") -> None:
    """Append ``message``'s record to the buffer. Replaces the prior record for
    the same message id (MJ edits messages in place — keep the newest state)."""
    rec = message_record(message, event)
    with _BUFFER_LOCK:
        for i, existing in enumerate(CHANNEL_BUFFER):
            if existing["message_id"] == rec["message_id"]:
                CHANNEL_BUFFER[i] = rec
                return
        CHANNEL_BUFFER.append(rec)


def recent_records(n: int) -> list[dict[str, Any]]:
    """The newest ``n`` records, newest first."""
    with _BUFFER_LOCK:
        return list(CHANNEL_BUFFER)[-n:][::-1]

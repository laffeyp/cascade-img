"""Parsing of inbound MJ Discord messages + the artifact downloader.

Everything here reads an already-arrived
``discord.Message`` (its content, attachments, components) or downloads an
attachment URL to disk — no live client, no job table — so it sits low in the
graph and ingest imports it downward.

Binding discipline: ``_download_to`` is monkeypatched by the test suite. Its
consumers (the ingest paths) reference it as ``discord_parse._download_to`` so a
``monkeypatch.setattr(discord_parse, "_download_to", ...)`` reaches them.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
from pathlib import Path

import requests

log = logging.getLogger("cascade_img.bridge.discord_parse")

UPSAMPLE_BTN_RE = re.compile(r"MJ::JOB::upsample::(\d+)::([0-9a-f-]+)")
PCT_RE = re.compile(r"\((\d+)%\)")

# Any MJ job uuid (8-4-4-4-12 hex). The NEW uuid minted for a derived result
# appears in its attachment filename and its midjourney.com/jobs/<uuid> link.
_MJ_UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")

# action_kind classified from MJ's content suffix. Substrings chosen to cover
# every sibling of each family ("Pan " matches Pan Left/Right/Up/Down; "Variations"
# matches Vary Subtle/Strong; "Upscaled " matches Upscale Subtle/Creative — MJ's
# suffix is "Upscaled (Subtle) by" / "Upscaled (Creative) by", NOT a bare "Upscaled
# by", so the marker must stop at the trailing space, not assume "by" follows
# immediately — 2026-06-10 live capture) — routing never depends on this label, so
# a wording drift downgrades the label, it does not misroute. animation is checked
# first (its content carries no "by" suffix, only the rewritten --video prompt).
_DERIVED_KIND_MARKERS: tuple[tuple[str, str], ...] = (
    ("--video", "animation"),
    ("Upscaled ", "upscale"),
    ("Variations", "variation"),
    ("Zoom Out", "zoom"),
    ("Pan ", "pan"),
)

# Action -> stable substring of the live custom_id MJ assigns the button on a
# SOLO upscaled-image message (captured 2026-06-02 from a live run). The full
# custom_id embeds the job uuid and
# is read off the live component at press time — these markers only *locate* the
# right button, they are never sent as-is. Distinct pairs (subtle/creative,
# low/high variation, Outpaint::50/::75) keep each lookup unambiguous.
_ACTION_MARKERS: dict[str, str] = {
    "upscale_subtle": "upsample_v7_2x_subtle",
    "upscale_creative": "upsample_v7_2x_creative",
    "vary_subtle": "low_variation",
    "vary_strong": "high_variation",
    "zoom_out_2x": "Outpaint::50",
    "zoom_out_1_5x": "Outpaint::75",
    "pan_left": "pan_left",
    "pan_right": "pan_right",
    "pan_up": "pan_up",
    "pan_down": "pan_down",
    "animate_high": "animate_high",
    "animate_low": "animate_low",
    "favorite": "BOOKMARK",
    # Native-video result buttons (captured live 2026-06-16, mj_capture_video_actions):
    # on the video grid — video_virtual_upscale::1-4 (extract a slot to a SOLO mp4);
    # on the SOLO video — animate_{high,low}_extend (+4s extend, grid-aligned ::N).
    # The grid's `reroll` button is deliberately NOT exposed: it generates a fresh,
    # untracked video whose own `--video` short-URL ack would be claimed by
    # _match_video and could mis-bind a pending /video job (review #9 F2) — re-roll
    # via generate_video instead, which is tracked and serialized.
    "video_upscale": "video_virtual_upscale",
    "extend_high": "animate_high_extend",
    "extend_low": "animate_low_extend",
}


def _download_to(url: str, path: Path) -> int:
    """Download ``url`` to ``path``; return the number of bytes written.

    Streams the response body to disk in 64 KB chunks so a large MJ grid
    (typical ~1-3 MB; upscales can reach 8 MB) never sits in memory in full.

    Atomic: the body streams to a sibling ``.part`` file and is ``os.replace``d
    into place only after a clean, fully-streamed response. A failure mid-stream
    removes the partial instead of leaving truncated bytes at ``path`` — which
    would otherwise poison the ``_safe_output_path`` existence check and orphan
    a half-image on disk.
    """
    total = 0
    tmp = path.with_suffix(path.suffix + ".part")
    try:
        with requests.get(url, timeout=30, stream=True) as resp:
            resp.raise_for_status()
            with tmp.open("wb") as f:
                for chunk in resp.iter_content(64 * 1024):
                    if chunk:
                        total += f.write(chunk)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    return total


def _extract_mj_uuid(components) -> str | None:
    """Pull the MJ job UUID out of any upsample button in the message."""
    for row in components or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            m = UPSAMPLE_BTN_RE.search(cid)
            if m:
                return m.group(2)
    return None


def _find_action_custom_id(message, action: str, slot: int | None = None) -> str | None:
    """Return the live ``custom_id`` of ``action``'s button on ``message``, or
    None if that button isn't present.

    Matches on the captured stable marker substring and returns the full live
    id (which embeds the slot's job uuid) read straight off the component — the
    bridge never hardcodes the uuid-bearing id. Buttons differ by MJ version, so
    a missing button yields None and the caller reports BUTTON_NOT_FOUND rather
    than pressing the wrong thing.

    ``video_upscale`` is the one action whose four buttons share ONE message (the
    video grid: ``video_virtual_upscale::1..4``), the slot living in the
    custom_id rather than in a separate per-slot message. For it the slot is
    folded into the marker so slot N presses ``::N``; other actions ignore slot
    here (their slot already picked the message)."""
    marker = _ACTION_MARKERS.get(action)
    if marker is None:
        # An action the bridge doesn't expose (e.g. the deferred video_reroll):
        # no marker, so it can't be located — degrade to BUTTON_NOT_FOUND rather
        # than raise. The action enum is the upstream gate; this is defense.
        return None
    if action == "video_upscale":
        marker = f"video_virtual_upscale::{slot or 1}"
    for row in getattr(message, "components", None) or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            if marker in cid:
                return cid
    return None


def _classify_derived(content: str) -> str:
    # animation's rewritten prompt carries MJ's video signature INSIDE the bolded
    # prompt ("... --motion high --video 1 --aspect 1:1**"); the other families
    # are named only in the suffix MJ appends after the prompt's closing "**".
    # Scan that suffix for them
    # so a family word inside the prompt body (e.g. an asset literally about "zoom")
    # cannot mislabel the result.
    #
    # Require BOTH "--video" and "--motion": a non-animation derived result echoes
    # the user's original prompt, so a user who wrote "--video" in their prompt
    # would otherwise mislabel every vary/zoom/pan/upscale as an animation. MJ's
    # actual animation rewrite always carries "--motion high|low", which a static
    # /imagine prompt does not.
    if "--video" in content and "--motion" in content:
        return "animation"
    tail = content.rsplit("**", 1)[-1]
    for marker, kind in _DERIVED_KIND_MARKERS:
        if kind != "animation" and marker in tail:
            return kind
    return "variation"  # a bare grid result with no recognized suffix


def _extract_derived_uuid(message) -> str | None:
    """The NEW MJ uuid minted for a derived result — read from the attachment
    filename (always present) with a content fallback (the jobs link)."""
    atts = getattr(message, "attachments", None) or []
    if atts:
        m = _MJ_UUID_RE.search(getattr(atts[0], "filename", "") or "")
        if m:
            return m.group(0)
    m = _MJ_UUID_RE.search(message.content or "")
    return m.group(0) if m else None


def _has_result_button(message) -> bool:
    """True if the message carries a real result button (U/V / upscale-variant /
    video), as opposed to a progress tracker's lone ``Cancel Job`` button or no
    buttons. This is the decisive final-vs-progress signal: MJ streams low-res
    progress frames (256x256 / 512x512) on a Cancel-only message, then the
    full-size final on a message bearing the action buttons (captured 2026-06-02)."""
    for row in getattr(message, "components", None) or []:
        for c in getattr(row, "children", []) or []:
            cid = getattr(c, "custom_id", "") or ""
            if cid and "CancelJob" not in cid:
                return True
    return False

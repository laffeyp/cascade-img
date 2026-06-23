"""Route a derived result (vary / zoom / pan / upscale-variant / animation)
back to its parent job.

Grounded in MJ's observed reply structure: MJ posts each derived result as a
Discord reply whose message_reference is the
SOLO upscaled-image message id (== Job.upscale_message_id). That reference is the
ONLY signal present on every family; the channel is shared, so recency/adjacency
matching is unsafe — a foreign job's animate interleaved into the capture window
would mis-route.

Binding discipline: the artifact downloader is called as
``discord_parse._download_to`` so the suite's
``monkeypatch.setattr(discord_parse, "_download_to", ...)`` reaches it.
"""

from __future__ import annotations

import logging
import os
import re

from cascade_img.backends.midjourney_discord.config import _cfg
from cascade_img.backends.midjourney_discord.jobs.job import Job
from cascade_img.backends.midjourney_discord.jobs.job_table import LOCK
from cascade_img.backends.midjourney_discord.jobs.persistence import _safe_output_path
from cascade_img.backends.midjourney_discord.transport import discord_parse
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.ingest_derived")


def _ingest_derived(parent: Job, message) -> None:
    """Download a derived result (vary/zoom/pan/upscale/animation) and attach it
    to its parent job. Skips progress frames and the favorite confirmation (which
    carry no full result). Claims each derived result once by its message id so a
    later edit of the same final does not re-download."""
    content = message.content or ""
    # Only the final carries a full-size attachment AND a result button with no
    # "(Waiting)"/"(N%)" marker. A favorite confirmation has no attachment; a
    # progress edit has only a Cancel button (or none) and a low-res preview.
    if not message.attachments:
        return
    if not discord_parse._has_result_button(message):
        return
    if discord_parse.PCT_RE.search(content) or "(Waiting to start)" in content:
        return

    c = _cfg()
    att = message.attachments[0]
    parent_message_id = getattr(getattr(message, "reference", None), "message_id", None)
    with LOCK:
        if any(d.get("message_id") == message.id for d in parent.derived):
            return  # already claimed/downloaded this derived result
        kind = discord_parse._classify_derived(content)
        # Artifact-aware override: a video derived (e.g. a video_virtual_upscale
        # SOLO mp4, or any video reply) IS an animation even when its echoed
        # prompt lacks --motion (a --loop video carries --video but no --motion,
        # so the content-only classifier would mislabel it "variation"). The
        # content_type is the ground truth. (caught live 2026-06-16)
        att_ct = getattr(att, "content_type", "") or ""
        att_name = getattr(att, "filename", "") or ""
        if kind != "animation" and (
            att_ct.startswith("video/") or att_name.lower().endswith((".mp4", ".mov", ".webm"))
        ):
            kind = "animation"
        mj_uuid = discord_parse._extract_derived_uuid(message) or ""
        # Reserve under LOCK (path="" sentinel) so a concurrent edit-dispatch of
        # the same final short-circuits at the membership check above.
        entry: dict = {
            "action_kind": kind,
            "mj_uuid": mj_uuid,
            "message_id": message.id,
            "path": "",
            "url": att.url,
            "content_type": getattr(att, "content_type", None),
            "width": getattr(att, "width", None),
            "height": getattr(att, "height", None),
            "bytes": 0,
        }
        parent.derived.append(entry)

    ext = os.path.splitext(getattr(att, "filename", "") or "")[1] or ".png"
    uuid8 = mj_uuid[:8] if mj_uuid else "result"
    out_path = _safe_output_path(
        output_dir=c.output_dir,
        asset_id=parent.asset_id,
        suffix=f"_{kind}_{uuid8}",
        ext=ext,
        request_token=parent.request_token,
        kind="derived",
        job_id=parent.job_id,
    )
    try:
        nbytes = discord_parse._download_to(att.url, out_path)
    except Exception as e:
        with LOCK:
            # Release the reservation so a later edit of the final can retry.
            parent.derived = [d for d in parent.derived if d.get("message_id") != message.id]
        emit(
            "MJ_DERIVED_FAILED",
            asset_id=parent.asset_id,
            job_id=parent.job_id,
            parent_message_id=parent_message_id,
            action_kind=kind,
            error_code=type(e).__name__,
            error_message=str(e)[:300],
        )
        log.error(f"[{parent.asset_id}] derived {kind} download failed: {e}")
        return

    with LOCK:
        entry["path"] = str(out_path)
        entry["bytes"] = nbytes
        parent.touch()
    log.info(f"[{parent.asset_id}] saved derived {kind} -> {out_path}")

    # A native-video SOLO (from video_virtual_upscale) carries its own
    # animate_*_extend buttons. Record it as an actionable surface so
    # mj_action(extend_high|extend_low, slot=N) can press it; the extended clip
    # then replies to this message and routes back via _job_by_upscale_message_id
    # (which scans upscale_message_ids). Recorded BEFORE the emit so an agent that
    # observes MJ_DERIVED_RECEIVED and immediately fires extend can't race a
    # not-yet-registered surface. (V-3, F3)
    if parent.kind == "video":
        sl = None
        for row in getattr(message, "components", None) or []:
            for ch in getattr(row, "children", None) or []:
                m = re.search(r"_extend::(\d+)", getattr(ch, "custom_id", "") or "")
                if m:
                    sl = int(m.group(1))
                    break
            if sl is not None:
                break
        if sl is not None:
            with LOCK:
                parent.upscale_message_ids[sl] = message.id
            emit(
                "MJ_ACTION_SURFACE_REGISTERED",
                asset_id=parent.asset_id,
                job_id=parent.job_id,
                slot=sl,
                message_id=message.id,
                surface_kind="video_solo",
            )

    emit(
        "MJ_DERIVED_RECEIVED",
        asset_id=parent.asset_id,
        job_id=parent.job_id,
        parent_message_id=parent_message_id,
        action_kind=kind,
        mj_uuid=mj_uuid,
        path=str(out_path),
        bytes=nbytes,
        content_type=getattr(att, "content_type", None) or "",
    )

"""Inbound MJ-message ingestion: the grid/video/progress/upscale state machine.

Extracted from bridge.py (sprint 023.9) by lift-and-shift — the flow is
unchanged; only the cross-module references are qualified. ``_ingest_message`` is
the exception-swallowing wrapper dispatched on the ingest pool from the Discord
event handlers; ``_ingest_message_impl`` is the actual state machine.

Binding discipline (the monkeypatch surface):
* the artifact downloader is called as ``discord_parse._download_to`` so
  ``monkeypatch.setattr(discord_parse, "_download_to", ...)`` reaches it;
* the loop accessor is called as ``runtime._running_loop`` and the press sender as
  ``discord_send._press_button`` for the same reason.
"""

from __future__ import annotations

import asyncio
import logging
import os

from cascade_img.backends.midjourney_discord import discord_parse, discord_send, runtime
from cascade_img.backends.midjourney_discord.capture import _capture_raw_message
from cascade_img.backends.midjourney_discord.config import MJ_BOT_ID, _cfg
from cascade_img.backends.midjourney_discord.ingest_derived import _ingest_derived
from cascade_img.backends.midjourney_discord.job import Status
from cascade_img.backends.midjourney_discord.job_table import LOCK
from cascade_img.backends.midjourney_discord.matching import (
    _job_by_message_id,
    _job_by_upscale_message_id,
    _match_grid,
    _match_upscale,
    _match_video,
    _video_result_parent,
)
from cascade_img.backends.midjourney_discord.persistence import _safe_output_path
from cascade_img.vocabulary import emit

log = logging.getLogger("cascade_img.bridge.ingest")


def _ingest_message(message, event: str = "message") -> None:
    """Process an MJ message, never propagating an exception. Dispatched on a
    thread pool from on_message / on_message_edit; a single malformed message
    (e.g. an unexpected attachment shape) must not break the ingest worker —
    catch and log it with context rather than let it surface only as a generic
    discord.py event-error log."""
    try:
        _ingest_message_impl(message, event)
    except Exception:
        log.exception(
            "[ingest] failed to process MJ message %s (event=%s); dropping it",
            getattr(message, "id", "?"),
            event,
        )


def _ingest_message_impl(message, event: str = "message"):
    """Update job state from an MJ message. ``event`` is "message" for a fresh
    message and "edit" when dispatched from ``on_message_edit`` — used only to
    tag the raw capture (``discord.Message`` is ``__slots__``-based, so
    the event cannot ride on the object; it must be passed as an argument)."""
    c = _cfg()
    if message.author.id != MJ_BOT_ID or message.channel.id != c.channel_id:
        return

    # Capture every MJ-bot message in the watched channel, verbatim,
    # BEFORE any routing return can drop it. on_message_edit funnels through
    # here too (it passes the AFTER message) with event="edit".
    _capture_raw_message(message, event)

    content = message.content or ""

    # A derived result (vary/zoom/pan/upscale/animation) is a
    # Discord reply to the SOLO upscaled-image message it was launched from. Route
    # by message_reference == a tracked job's upscale_message_id — the only signal
    # present on every family; recency is unsafe (shared channel). Handled and
    # returned here so it never reaches the grid/upscale matchers (the original
    # SOLO and grid messages reference other ids, so they fall through untouched).
    ref_id = getattr(getattr(message, "reference", None), "message_id", None)
    if ref_id is not None:
        derived_parent = _job_by_upscale_message_id(ref_id) or _video_result_parent(ref_id)
        if derived_parent is not None:
            _ingest_derived(derived_parent, message)
            return

    job = _job_by_message_id(message.id)
    if job is None:
        job = _match_grid(content)
        if job is not None:
            with LOCK:
                job.message_id = message.id
                job.status = Status.PROGRESS
                job.touch()
            log.info(f"[{job.asset_id}] matched grid message {message.id} via {job.match_path}")
            emit(
                "GRID_MATCHED",
                asset_id=job.asset_id,
                job_id=job.job_id,
                message_id=message.id,
                match_path=job.match_path or "unknown",
            )

    # Native video: bound by MJ's echoed short URL (no --no token), routed into
    # the same PROGRESS lifecycle below. No GRID_MATCHED — VIDEO_REQUESTED fired
    # at /video; the trace is VIDEO_REQUESTED -> VIDEO_RECEIVED -> JOB_COMPLETED.
    if job is None:
        job = _match_video(content)
        if job is not None:
            with LOCK:
                job.message_id = message.id
                if job.status in (Status.QUEUED, Status.SUBMITTED):
                    job.status = Status.PROGRESS
                job.touch()
            log.info(f"[{job.asset_id}] matched video message {message.id} via {job.match_path}")

    if job is not None and job.status in (Status.PROGRESS, Status.SUBMITTED):
        pct = discord_parse.PCT_RE.search(content)
        if pct:
            with LOCK:
                job.progress = f"{pct.group(1)}%"
                job.touch()
            return
        if "(Waiting to start)" in content:
            with LOCK:
                job.progress = "queued"
                job.touch()
            return
        if message.attachments and not discord_parse._has_result_button(message):
            # A low-res progress frame can carry an attachment but only a lone
            # Cancel button (no U/V result buttons). Without this guard it could
            # race the real final grid and win the reservation below, downloading
            # a 256x256 preview as the grid. Result buttons are the decisive
            # final-vs-progress signal (see _has_result_button); treat anything
            # without them as a still-in-progress frame and wait for the final.
            return
        if message.attachments:
            # Claim the grid exactly once. on_message and on_message_edit
            # both dispatch _ingest_message via run_in_executor; for the same
            # MJ message both can race here and double-download / double-
            # upscale. Reserve job.grid_path under LOCK before any I/O so a
            # concurrent ingest short-circuits.
            with LOCK:
                if job.grid_path is not None or job.status not in (
                    Status.PROGRESS,
                    Status.SUBMITTED,
                ):
                    return
                job.grid_path = ""  # reservation sentinel — closes the window

            att = message.attachments[0]
            ext = os.path.splitext(att.filename)[1] or ".png"
            suffix = "_grid" if job.upscale else ""
            grid_path = _safe_output_path(
                output_dir=c.output_dir,
                asset_id=job.asset_id,
                suffix=suffix,
                ext=ext,
                request_token=job.request_token,
                kind="grid",
                job_id=job.job_id,
            )
            try:
                grid_bytes = discord_parse._download_to(att.url, grid_path)
            except Exception as e:
                # Release the reservation so a retry (or the operator's
                # re-fire) doesn't see a permanently-claimed slot.
                with LOCK:
                    if job.grid_path == "":
                        job.grid_path = None
                if job.kind == "video":
                    job._fail("VIDEO_DOWNLOAD_FAILED", f"video download failed: {e}")
                else:
                    job._fail("GRID_DOWNLOAD_FAILED", f"grid download failed: {e}")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            with LOCK:
                job.grid_url = att.url
                job.grid_path = str(grid_path)
                job.touch()
            # A video result is one animated webp, not a 2x2 grid — emit the
            # honest VIDEO_RECEIVED (same payload shape) instead of GRID_RECEIVED.
            emit(
                "VIDEO_RECEIVED" if job.kind == "video" else "GRID_RECEIVED",
                asset_id=job.asset_id,
                job_id=job.job_id,
                path=str(grid_path),
                bytes=grid_bytes,
            )

            if not job.upscale:
                with LOCK:
                    job.image_path = str(grid_path)
                    job.image_url = att.url
                log.info(f"[{job.asset_id}] saved grid -> {grid_path}")
                job._complete()
                return

            mj_uuid = discord_parse._extract_mj_uuid(message.components)
            if not mj_uuid:
                job._fail(
                    "MJ_UUID_MISSING",
                    "could not find MJ job uuid in grid components",
                )
                log.error(f"[{job.asset_id}] {job.error}")
                return

            slots = [1, 2, 3, 4] if job.upscale == "all" else [int(job.upscale)]
            with LOCK:
                job.mj_job_uuid = mj_uuid
                job.upscale_pending = list(slots)
                job.status = Status.UPSCALING
                job.progress = "upscaling"
                job.touch()
            log.info(
                f"[{job.asset_id}] grid done, requesting upscale "
                f"slots={slots} mj_uuid={mj_uuid[:8]}..."
            )

            guild_id = str(message.guild.id) if message.guild else None
            for n in slots:
                emit(
                    "UPSCALE_REQUESTED",
                    asset_id=job.asset_id,
                    job_id=job.job_id,
                    slot=n,
                    mj_job_uuid_prefix=mj_uuid[:8],
                )

            # Fire all button presses concurrently — gather lets a slow Discord
            # interaction on slot 1 not stall slot 2/3/4. return_exceptions=True
            # collects per-slot failures without aborting the others.
            async def _press_all_slots():
                coros = [
                    discord_send._press_button(
                        message.id, f"MJ::JOB::upsample::{n}::{mj_uuid}", guild_id
                    )
                    for n in slots
                ]
                return await asyncio.gather(*coros, return_exceptions=True)

            try:
                gather_fut = asyncio.run_coroutine_threadsafe(
                    _press_all_slots(), runtime._running_loop()
                )
                # 35s budget: 30s per-request timeout in _post_interaction +
                # 5s gather/scheduling slack.
                results = gather_fut.result(timeout=35)
            except Exception as e:
                # The gather itself blew up (shouldn't happen with
                # return_exceptions=True except on loop death / timeout).
                job._fail(
                    "UPSCALE_BUTTON_FAILED",
                    f"upscale gather failed: {type(e).__name__}: {e}",
                )
                log.error(f"[{job.asset_id}] {job.error}")
                return

            failed_slots: list[tuple[int, str]] = []
            succeeded_slots: list[int] = []
            for n, result in zip(slots, results, strict=True):
                if isinstance(result, BaseException):
                    code = type(result).__name__
                    msg = str(result) or repr(result)
                    failed_slots.append((n, f"{code}: {msg}"))
                    emit(
                        "UPSCALE_PRESS_FAILED",
                        asset_id=job.asset_id,
                        job_id=job.job_id,
                        slot=n,
                        error_code=code,
                        error_message=msg[:500],
                    )
                elif result.status_code not in (200, 204):
                    code = f"HTTP_{result.status_code}"
                    msg = result.text[:500] if hasattr(result, "text") else ""
                    failed_slots.append((n, f"{code}: {msg[:200]}"))
                    emit(
                        "UPSCALE_PRESS_FAILED",
                        asset_id=job.asset_id,
                        job_id=job.job_id,
                        slot=n,
                        error_code=code,
                        error_message=msg,
                    )
                else:
                    succeeded_slots.append(n)

            with LOCK:
                for n, detail in failed_slots:
                    job.upscale_press_failures[n] = detail
                    if n in job.upscale_pending:
                        job.upscale_pending.remove(n)
                job.touch()

            if not succeeded_slots:
                # Every slot's press failed; the job has nothing to wait for.
                terminal_code = (
                    "UPSCALE_BUTTON_FAILED" if len(slots) == 1 else "UPSCALE_ALL_BUTTONS_FAILED"
                )
                detail = "; ".join(f"U{n}: {d}" for n, d in failed_slots)
                job._fail(terminal_code, f"all upscale presses failed — {detail}")
                log.error(f"[{job.asset_id}] {job.error}")
                return

            if failed_slots:
                log.warning(
                    f"[{job.asset_id}] {len(failed_slots)}/{len(slots)} "
                    f"upscale presses failed "
                    f"(U{','.join(str(n) for n, _ in failed_slots)}); "
                    f"continuing to wait for "
                    f"U{','.join(str(n) for n in succeeded_slots)}"
                )
            return

    matched = _match_upscale(content)
    if matched and message.attachments:
        parent, idx = matched
        # Claim-once, mirroring the grid and derived paths. on_message and
        # on_message_edit both dispatch _ingest_message via run_in_executor and
        # the SOLO upscale message arrives as a create plus several edits, so
        # two threads can both clear _match_upscale (a pure read) for the same
        # slot. Reserve the slot under LOCK before any I/O — and re-check inside
        # the lock — so a concurrent dispatch short-circuits instead of
        # double-downloading and double-completing (which would breach the
        # locked terminal invariant with a second UPSCALE_RECEIVED/JOB_COMPLETED).
        with LOCK:
            if (
                idx in parent.upscale_paths
                or idx not in parent.upscale_pending
                or parent.status != Status.UPSCALING
            ):
                return
            parent.upscale_paths[idx] = ""  # reservation sentinel — closes the window
        att = message.attachments[0]
        ext = os.path.splitext(att.filename)[1] or ".png"
        suffix = f"_u{idx}" if parent.upscale == "all" else ""
        out_path = _safe_output_path(
            output_dir=c.output_dir,
            asset_id=parent.asset_id,
            suffix=suffix,
            ext=ext,
            request_token=parent.request_token,
            kind="upscale",
            job_id=parent.job_id,
        )
        try:
            up_bytes = discord_parse._download_to(att.url, out_path)
        except Exception as e:
            # Partial-tolerance, mirroring the press path (see the press-failure
            # handling above): under upscale="all" one slot's download failure
            # must not discard siblings that already landed or are still in
            # flight. Record the per-slot failure, drop this slot from pending,
            # and only fail the whole job when NO slot can still land — nothing
            # downloaded and nothing pending. The single-slot upscale case (one
            # slot total) still fails the job, since that slot was the only
            # result expected.
            with LOCK:
                # Release the reservation so a later edit of the same slot can
                # re-claim instead of seeing a permanently-reserved sentinel.
                if parent.upscale_paths.get(idx) == "":
                    parent.upscale_paths.pop(idx, None)
                parent.upscale_download_failures[idx] = f"{type(e).__name__}: {e}"
                if idx in parent.upscale_pending:
                    parent.upscale_pending.remove(idx)
                landed = any(v for v in parent.upscale_paths.values())
                remaining = list(parent.upscale_pending)
                parent.touch()
            # Per-slot incident, fired for every failed download (mirrors the
            # press path's UPSCALE_PRESS_FAILED) so the download surface has the
            # same observability — the job's survival decision follows below.
            emit(
                "UPSCALE_DOWNLOAD_DROPPED",
                asset_id=parent.asset_id,
                job_id=parent.job_id,
                slot=idx,
                error_code=type(e).__name__,
                error_message=str(e)[:500],
            )
            if not landed and not remaining:
                # Nothing downloaded and nothing left in flight — no path to a result.
                detail = "; ".join(
                    f"U{n}: {d}" for n, d in sorted(parent.upscale_download_failures.items())
                )
                parent._fail(
                    "UPSCALE_DOWNLOAD_FAILED",
                    f"all upscale downloads failed — {detail}",
                )
                log.error(f"[{parent.asset_id}] {parent.error}")
                return
            if not remaining:
                # This failed slot was the LAST pending one, but earlier slots
                # landed — complete the job on the survivors instead of leaving it
                # stuck in UPSCALING (which only the inflight reaper would catch,
                # much later). Mirrors the success path's complete-on-empty-pending.
                log.warning(
                    f"[{parent.asset_id}] upscale U{idx} download failed "
                    f"({type(e).__name__}: {e}); completing on survivors "
                    f"{sorted(k for k, v in parent.upscale_paths.items() if v)}"
                )
                parent._complete()
                return
            log.warning(
                f"[{parent.asset_id}] upscale U{idx} download failed "
                f"({type(e).__name__}: {e}); continuing — "
                f"landed={sorted(k for k, v in parent.upscale_paths.items() if v)} "
                f"pending={remaining}"
            )
            return

        with LOCK:
            parent.upscale_paths[idx] = str(out_path)
            # Record the SOLO message id per slot (every SOLO carries the same
            # vary/zoom/pan/animate/favorite action set, bound to its own uuid).
            parent.upscale_message_ids[idx] = message.id
            if parent.image_path is None:
                # First upscale to land wins the canonical image slot — and the
                # canonical SOLO message tracks the SAME slot, so mj_action and
                # the promoted image_path always refer to one image.
                parent.image_path = str(out_path)
                parent.image_url = att.url
                parent.upscale_message_id = message.id
            if idx in parent.upscale_pending:
                parent.upscale_pending.remove(idx)
            parent.touch()
            remaining = list(parent.upscale_pending)

        log.info(f"[{parent.asset_id}] saved upscale U{idx} -> {out_path}")
        emit(
            "MJ_ACTION_SURFACE_REGISTERED",
            asset_id=parent.asset_id,
            job_id=parent.job_id,
            slot=idx,
            message_id=message.id,
            surface_kind="image_upscale",
        )
        emit(
            "UPSCALE_RECEIVED",
            asset_id=parent.asset_id,
            job_id=parent.job_id,
            slot=idx,
            path=str(out_path),
            bytes=up_bytes,
        )
        if not remaining:
            log.info(f"[{parent.asset_id}] all upscales complete")
            parent._complete()

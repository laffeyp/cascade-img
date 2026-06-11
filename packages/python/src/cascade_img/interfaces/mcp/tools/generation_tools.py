"""MCP tools that drive generation against the running bridge daemon.

These funnel through the shared sync backend (``_envelope._backend``); the
envelope dispatches the blocking HTTP calls on a worker thread.
"""

from __future__ import annotations

from typing import Any

from cascade_img.interfaces.mcp import _envelope


async def imagine(
    prompt: str,
    asset_id: str,
    upscale: str | None = None,
    idempotency_key: str | None = None,
) -> dict[str, Any]:
    """Fire one generation against the running bridge. Backend is sync —
    _run_tool dispatches it via asyncio.to_thread.

    ``idempotency_key`` makes the call safe to RETRY: pass the same key when
    re-issuing a generation you are not sure landed (e.g. one whose tool call was
    cancelled mid-flight — the bridge may have already submitted it on a worker
    thread), and the bridge replays the existing job instead of submitting and
    billing Midjourney twice. The result then carries ``idempotent_replay:
    true``. Leave it unset (or use a fresh key) for a genuinely new roll —
    re-rolls are intentionally NOT deduplicated by asset_id."""
    return await _envelope._run_tool(
        "imagine",
        _envelope._backend.imagine,
        prompt=prompt,
        asset_id=asset_id,
        upscale=upscale,
        idempotency_key=idempotency_key,
    )


async def wait(job_id: str, timeout: int = 180) -> dict[str, Any]:
    """Block until the job hits ``done`` or ``failed`` or the timeout fires.
    Returns the full job record under ``result``.

    A timeout is NOT a failure: the envelope is still ``{ok: true}`` but the
    result carries ``timed_out: true`` and a non-terminal ``status`` (the job
    may still be rendering). Branch on ``result.status`` and ``result.timed_out``
    — ``ok: true`` alone does not mean the job finished. Do not re-roll on a
    timeout (it double-bills); poll ``wait``/``status`` again instead."""
    return await _envelope._run_tool(
        "wait", _envelope._backend.wait, job_id=job_id, timeout=timeout
    )


async def status(job_id: str) -> dict[str, Any]:
    """Non-blocking status read."""
    return await _envelope._run_tool("status", _envelope._backend.status, job_id=job_id)


async def bridge_health() -> dict[str, Any]:
    """Check whether the bridge daemon is up and the Discord WebSocket is
    connected."""
    return await _envelope._run_tool("bridge_health", _envelope._backend.health)


async def mj_action(job_id: str, action: str, slot: int | None = None) -> dict[str, Any]:
    """Press a Midjourney response-message button on a completed job's upscaled
    image — driving the buttons a human would otherwise click. ``action`` is one
    of: ``upscale_subtle``, ``upscale_creative``, ``vary_subtle``,
    ``vary_strong``, ``zoom_out_2x``, ``zoom_out_1_5x``, ``pan_left``,
    ``pan_right``, ``pan_up``, ``pan_down``, ``animate_high``, ``animate_low``,
    ``favorite``. ``slot`` (1-4) targets a specific SOLO image when the job was
    run with ``upscale="all"``; omit it for the canonical image.

    Requires the job to have an upscaled image (run ``imagine`` with
    ``upscale=1-4`` or ``"all"`` first); otherwise the envelope carries
    ``error.code == "NO_UPSCALED_IMAGE"``. The pressed action's result (a new
    grid, or for ``animate_*`` an animated webp) is routed back to the job and
    recorded in its ``derived`` list (read it via ``status``)."""
    return await _envelope._run_tool(
        "mj_action", _envelope._backend.action, job_id=job_id, action=action, slot=slot
    )

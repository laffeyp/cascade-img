"""MCP tools for catching up on human activity in the MJ channel.

The human directing the agent can act in Discord directly — press U4 by hand,
fire a Vary. Those results never reach the tracked-job surface on their own.
``channel_recent`` shows what happened; ``adopt_message`` claims a result into
the pipeline so the normal tools (``status``, curation, ``mj_action``) work on
it, and records the human's move in the prompt log so working memory stays
truthful.
"""

from __future__ import annotations

from typing import Any

from cascade_img.interfaces.mcp import _envelope


async def channel_recent(n: int = 10) -> dict[str, Any]:
    """See the newest Midjourney results in the channel, newest first —
    including ones the HUMAN made by hand in Discord (a U-press, a Vary), which
    no tracked job knows about. Each record carries ``tracked_job_id`` (``null``
    means "this happened without you" — a catch-up candidate), the parsed
    routing token, the result ``kind`` (grid / solo / video / other), the
    attachment, and ``buttons`` — the ``mj_action`` names present on the
    message, i.e. what adopting it would unlock. Read-only; capped at 50.
    Follow up with ``adopt_message`` to act on an untracked result."""
    return await _envelope._run_tool("channel_recent", _envelope._backend.channel_recent, n=n)


async def adopt_message(message_id: str, asset_id: str) -> dict[str, Any]:
    """Claim an existing MJ channel message (found via ``channel_recent``) into
    the job table as a tracked job. Downloads its artifact to the standard
    output path and registers the message as the job's action surface: adopting
    a SOLO ("Image #N") unlocks ``vary_*``/``zoom_*``/``pan_*``/``animate_*``
    via ``mj_action``; adopting a video unlocks ``video_upscale`` then
    ``extend_*``; adopting a grid yields the artifact for cropping (its U-press
    is not wired — crop_grid gives the same pixels on a V8.1 ``--hd`` render).
    Idempotent per message: adopting one that is already tracked returns
    ``ALREADY_TRACKED`` with the existing ``job_id``. On success a prompt-log
    record with ``origin: "human_in_discord"`` is appended so the next
    ``read_prompt_log`` shows the director's move."""

    def go():
        result = _envelope._backend.adopt(message_id=message_id, asset_id=asset_id)
        _envelope._log.append(
            asset_id=asset_id,
            prompt=f"adopted channel message {message_id}",
            backend="midjourney_discord",
            job_id=result.get("job_id"),
            outputs={"image_path": result.get("image_path"), "kind": result.get("kind")},
            origin="human_in_discord",
        )
        return result

    return await _envelope._run_tool("adopt_message", go)

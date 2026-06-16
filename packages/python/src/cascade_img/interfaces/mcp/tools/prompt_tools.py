"""MCP tool: compose a Midjourney prompt from composable parts."""

from __future__ import annotations

from typing import Any

from cascade_img.interfaces.mcp import _envelope
from cascade_img.prompt.composer import (
    IdentityStack,
    ParamStack,
    StyleStack,
    Subject,
)


async def compose_prompt(
    subject: str,
    constraints: list[str] | None = None,
    moodboard: str | None = None,
    sref: str | None = None,
    sw: int | None = None,
    stylize: int | None = None,
    style_raw: bool = True,
    oref: str | None = None,
    ow: int = 100,
    aspect_ratio: str = "1:1",
    negatives: list[str] | None = None,
    image_prompts: list[str] | None = None,
    image_weight: float | None = None,
    tile: bool = False,
    exp: int | None = None,
    chaos: int | None = None,
    weird: int | None = None,
    quality: int | None = None,
    hd: bool = False,
    sd: bool = False,
    seed: int | None = None,
    version: str | None = None,
) -> dict[str, Any]:
    """Compose a Midjourney prompt from composable prompt parts. Returns
    ``{ok, result: {prompt}}``.

    ``version`` selects the model: ``'8.1'``, ``'8'``, or ``'7'``; omit it
    (``None``) to use the composer's default model (V8.1). Features are
    version-gated and a mismatch returns a
    structured ValueError through the envelope: ``oref``/``ow`` and ``quality``
    require ``version='7'`` (V8.1 dropped Omni Reference and ``--q``);
    ``hd``/``sd`` (V8.1 native 2048px / 1024px rendering) require the V8 family.

    Beyond the style/identity parts: ``sw`` is the style-reference weight
    (``--sw``, only meaningful with ``sref``); ``negatives`` becomes a single
    ``--no`` clause; ``image_prompts`` are reference URLs prepended to the
    prompt with optional ``image_weight`` (``--iw``); ``exp``/``tile``/
    ``chaos``/``weird``/``quality``/``hd``/``sd``/``seed`` are render controls.
    Out-of-range values return a structured ValueError through the envelope."""

    def go():
        prompt = _envelope._composer.compose(
            Subject(
                text=subject,
                constraints=constraints or [],
                negatives=negatives or [],
                image_prompts=image_prompts or [],
                image_weight=image_weight,
            ),
            style=StyleStack(
                moodboard=moodboard,
                sref=sref,
                sw=sw,
                stylize=stylize,
                style_raw=style_raw,
            ),
            identity=IdentityStack(oref=oref, ow=ow) if oref else None,
            params=ParamStack(
                tile=tile,
                exp=exp,
                chaos=chaos,
                weird=weird,
                quality=quality,
                hd=hd,
                sd=sd,
                seed=seed,
            ),
            aspect_ratio=aspect_ratio,
            version=version,
        )
        return {"prompt": prompt}

    return await _envelope._run_tool("compose_prompt", go)


async def compose_video(
    image_url: str,
    text: str | None = None,
    motion: str | None = None,
    raw: bool = False,
    loop: bool = False,
    end_frame: str | None = None,
    batch_size: int | None = None,
) -> dict[str, Any]:
    """Compose a Midjourney native **video** prompt (own image -> 5s clip).
    Returns ``{ok, result: {prompt}}``.

    ``image_url`` is the starting frame (required). Video prompts accept ONLY
    video-specific params: ``motion`` (``"low"``/``"high"``), ``raw``, ``loop``
    (reuse the start frame as the end frame), ``end_frame`` (a different end
    frame URL — mutually exclusive with ``loop``), and ``batch_size`` (1/2/4).
    Image params are not accepted (MJ strips them under ``--video``). Conflicts
    return a structured ValueError through the envelope.

    Note: this composes the prompt string; firing native video through the
    bridge lands in a later step. To animate an already-generated upscale today,
    use ``mj_action(job_id, "animate_high"|"animate_low")`` instead."""

    def go():
        prompt = _envelope._composer.compose_video(
            image_url=image_url,
            text=text,
            motion=motion,
            raw=raw,
            loop=loop,
            end_frame=end_frame,
            batch_size=batch_size,
        )
        return {"prompt": prompt}

    return await _envelope._run_tool("compose_video", go)

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
    seed: int | None = None,
) -> dict[str, Any]:
    """Compose a Midjourney v7 prompt from composable prompt parts. Returns
    ``{ok, result: {prompt}}``.

    Beyond the style/identity parts: ``sw`` is the style-reference weight
    (``--sw``, only meaningful with ``sref``); ``negatives`` becomes a single
    ``--no`` clause; ``image_prompts`` are reference URLs prepended to the
    prompt with optional ``image_weight`` (``--iw``); ``exp``/``tile``/
    ``chaos``/``weird``/``quality``/``seed`` are render controls.
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
                seed=seed,
            ),
            aspect_ratio=aspect_ratio,
        )
        return {"prompt": prompt}

    return await _envelope._run_tool("compose_prompt", go)

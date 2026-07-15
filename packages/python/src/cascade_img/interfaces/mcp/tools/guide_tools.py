"""The activation tool — returns the full operating manual in one call.

cascade-img is operated by an LLM agent, and an agent's knowledge is whatever is
in its context. ``cascade_guide`` returns the entire operator corpus (via
``cascade_img.guide.load_guide``) so that reading the manual is a single tool
call. The generation and curation tools are gated until it has been read this
session (see ``_envelope`` ``GuideUnreadError`` / ``_GATED_TOOLS``).
"""

from __future__ import annotations

from typing import Any

from cascade_img.guide import load_guide
from cascade_img.interfaces.mcp import _envelope


async def cascade_guide() -> dict[str, Any]:
    """START HERE — call this first, before any other tool.

    Returns the complete cascade-img operating manual, in full: the per-asset
    loop, every tool and when to use it, the Midjourney prompt-parameter surface,
    the version split, and the failure-code-to-action table. You, the agent, are
    the operator — you cannot drive the other tools correctly without this. The
    generation, composition, and curation tools return ``GUIDE_UNREAD`` until you
    have called this once in the session. The manual is written to be read in one
    pass; read all of it."""

    async def go() -> dict[str, Any]:
        text = load_guide()
        _envelope._guide_read = True
        return {"guide": text}

    return await _envelope._run_tool("cascade_guide", go)

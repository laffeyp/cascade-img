"""The operator guide, shipped as package data and served in full.

cascade-img is operated by an LLM agent. Everything the agent needs to drive the
tools — the loop, every tool, the parameter surface, the failure-to-action table
— lives in these documents. :func:`load_guide` returns them concatenated, in
full, loaded from the installed package via ``importlib.resources`` (works from a
built wheel; no repo checkout required). The MCP ``cascade_guide`` tool returns
this string, so that reading the manual is a single tool call.

The source of truth is the repo-root docs; ``tools/sync_guide_docs.py`` mirrors
them into this directory and its ``--check`` mode gates against drift.
"""

from __future__ import annotations

from importlib.resources import files

# Ordered manifest: (section key, bundled filename, display title). The order is
# the reading order — the loop-and-tools overview (AGENTS) sits first, at the
# high-attention head of the returned string.
_MANIFEST: tuple[tuple[str, str, str], ...] = (
    ("AGENTS", "AGENTS.md", "AGENTS — operator guide"),
    ("RUNBOOK", "RUNBOOK.md", "RUNBOOK — setup, bring-up, failure modes"),
    ("CAPABILITIES", "CAPABILITIES.md", "CAPABILITIES — prompt parameters and actions"),
    ("ARCHITECTURE", "ARCHITECTURE.md", "ARCHITECTURE — how the pieces fit"),
    ("example-single", "example-generate-a-single-image.md", "EXAMPLE — a single image"),
    ("example-batch", "example-generate-a-batch.md", "EXAMPLE — a batch sharing one style"),
    ("example-video", "example-generate-a-video.md", "EXAMPLE — a video"),
    ("AGENT_RUNDOWN", "AGENT_RUNDOWN.md", "AGENT_RUNDOWN — paste-in briefing prompt"),
)

_SECTIONS = {key: (fname, title) for key, fname, title in _MANIFEST}


def _read(filename: str) -> str:
    return (files("cascade_img.guide") / filename).read_text(encoding="utf-8")


def guide_sections() -> list[str]:
    """The section keys accepted by ``load_guide(section=...)``, in reading order."""
    return [key for key, _fname, _title in _MANIFEST]


def load_guide(section: str | None = None) -> str:
    """Return the operator guide, loaded from the installed package.

    ``section=None`` returns the full corpus — every document concatenated in
    reading order, each under a ``# ===== <title> =====`` header. Pass a section
    key (see :func:`guide_sections`) to return a single document. An unknown
    section raises ``ValueError`` naming the valid keys.
    """
    if section is not None:
        if section not in _SECTIONS:
            raise ValueError(
                f"unknown guide section {section!r}; valid sections: {', '.join(guide_sections())}"
            )
        fname, title = _SECTIONS[section]
        return f"# ===== {title} =====\n\n{_read(fname)}"

    parts = [f"# ===== {title} =====\n\n{_read(fname)}" for _key, fname, title in _MANIFEST]
    return "\n\n".join(parts)

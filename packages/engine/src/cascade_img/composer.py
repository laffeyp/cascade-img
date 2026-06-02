"""PromptComposer — turn structured facets into a Midjourney v7 prompt string.

The single most-differentiated piece of cascade-img. No other OSS tool exposes
V7 facets (``--p``/``--sref``/``--oref``/``--ow``) as independently composable
inputs. The consumer supplies subject text, an optional style stack, an
optional identity stack, and an aspect ratio. The composer assembles the
backend-specific prompt string.

For v0.1, the only backend is Midjourney Discord, so the composition emits
MJ V7 syntax. When a second backend lands (Flux, DALL-E), the composer grows
a per-backend ``compose_for(backend)`` path.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from cascade_img.instrumentation.sdd import emit


@dataclass
class Subject:
    """The thing being depicted. Free-text plus optional explicit constraints
    that get folded into the prompt for emphasis (MJ weights repeated concepts
    higher — the Sprint 4.0 "pixel-art sprite, low-resolution, limited palette"
    pattern is exactly this)."""

    text: str
    constraints: list[str] = field(default_factory=list)


@dataclass
class StyleStack:
    """Style facets. None values are omitted from the prompt.

    - ``moodboard`` is MJ's ``--p`` personalization profile code (e.g.
      ``m7458053701014388751``). Pass the code only, without the leading ``m``
      if MJ requires it stripped, or with — the composer doesn't enforce a
      prefix convention.
    - ``sref`` is MJ's ``--sref`` style-reference URL or integer code.
    - ``stylize`` is MJ's ``--s`` (0-1000); default 100 if omitted in MJ.
    - ``style_raw`` toggles the ``--style raw`` flag that suppresses MJ's
      default opinion injection; True for cascade-img's locked-style use case.
    """

    moodboard: Optional[str] = None
    sref: Optional[str] = None
    stylize: Optional[int] = None
    style_raw: bool = True


@dataclass
class IdentityStack:
    """Omni-reference identity lock (V7's ``--oref``/``--ow``).

    ``ow`` is omni-weight (0-1000). Default 100 is loose; 400 is tight identity
    match; 1000 is maximum — the Sprint 4.7 progression on the wing-frame work.
    """

    oref: Optional[str] = None
    ow: int = 100


class PromptComposer:
    """Compose v7 prompts from facets.

    Stateless. Hold one in a module-level singleton if you want, or instantiate
    per call — there's nothing to share.
    """

    def compose(
        self,
        subject: Subject,
        style: Optional[StyleStack] = None,
        identity: Optional[IdentityStack] = None,
        aspect_ratio: str = "1:1",
    ) -> str:
        """Return a Midjourney v7 prompt string."""
        # Subject text + constraints fold together. Repeating constraints
        # is a Sprint-4.0 lesson: MJ weights repeated concepts higher.
        parts: list[str] = [subject.text.strip()]
        for c in subject.constraints:
            c = c.strip()
            if c:
                parts.append(c)
        subject_text = ", ".join(parts)

        flags: list[str] = []
        flags.append(f"--ar {aspect_ratio}")
        flags.append("--v 7")

        facets_used: list[str] = []

        if style is not None:
            if style.style_raw:
                flags.append("--style raw")
            if style.moodboard:
                flags.append(f"--p {style.moodboard}")
                facets_used.append("moodboard")
            if style.sref:
                flags.append(f"--sref {style.sref}")
                facets_used.append("sref")
            if style.stylize is not None:
                flags.append(f"--s {style.stylize}")
                facets_used.append("stylize")
        else:
            flags.append("--style raw")

        if identity is not None and identity.oref:
            flags.append(f"--oref {identity.oref}")
            flags.append(f"--ow {identity.ow}")
            facets_used.extend(["oref", "ow"])

        prompt = subject_text + " " + " ".join(flags)
        emit(
            "PROMPT_COMPOSED",
            facets_used=facets_used,
            aspect_ratio=aspect_ratio,
            prompt_chars=len(prompt),
        )
        return prompt

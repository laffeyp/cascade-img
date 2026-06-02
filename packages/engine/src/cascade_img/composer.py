"""Assemble Midjourney v7 prompt strings from structured facets.

The consumer supplies a subject, an optional style stack, an optional
identity stack, and an aspect ratio. The composer emits the backend-specific
prompt string. v0.1 emits Midjourney v7 syntax (``--ar``, ``--v``,
``--style``, ``--p``, ``--sref``, ``--s``, ``--oref``, ``--ow``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade_img.vocabulary import emit


@dataclass
class Subject:
    """The thing being depicted.

    ``constraints`` are folded into the prompt as comma-separated phrases
    after ``text``; Midjourney weights repeated concepts higher, so naming
    style constraints explicitly (e.g. "pixel-art sprite", "limited palette")
    pulls the render in that direction more reliably than a single phrase.
    """

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

    moodboard: str | None = None
    sref: str | None = None
    stylize: int | None = None
    style_raw: bool = True


@dataclass
class IdentityStack:
    """Omni-reference identity lock (V7's ``--oref``/``--ow``).

    ``ow`` is omni-weight (0-1000). 100 is loose, 400 is tight identity
    match, 1000 is maximum.
    """

    oref: str | None = None
    ow: int = 100


class PromptComposer:
    """Compose v7 prompts from facets.

    Stateless. Hold one in a module-level singleton if you want, or instantiate
    per call — there's nothing to share.
    """

    def compose(
        self,
        subject: Subject,
        style: StyleStack | None = None,
        identity: IdentityStack | None = None,
        aspect_ratio: str = "1:1",
    ) -> str:
        """Return a Midjourney v7 prompt string."""
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

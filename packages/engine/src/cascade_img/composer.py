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
    """Style parts. None values are omitted from the prompt.

    - ``moodboard`` is Midjourney's ``--p`` personalization profile code
      (e.g. ``m7458053701014388751``). The composer doesn't enforce a
      prefix convention; pass the code as-is.
    - ``sref`` is Midjourney's ``--sref`` style-reference URL or integer code.
    - ``stylize`` is Midjourney's ``--s`` value. Midjourney accepts 0-1000;
      validated at construction. Default 100 if omitted at Midjourney's end.
    - ``style_raw`` toggles the ``--style raw`` flag that suppresses
      Midjourney's default opinion injection.
    """

    moodboard: str | None = None
    sref: str | None = None
    stylize: int | None = None
    style_raw: bool = True

    def __post_init__(self) -> None:
        if self.stylize is not None and not 0 <= self.stylize <= 1000:
            raise ValueError(
                f"StyleStack.stylize must be 0-1000 per Midjourney's --s "
                f"range; got {self.stylize!r}."
            )


@dataclass
class IdentityStack:
    """Omni-reference identity lock (Midjourney v7's ``--oref``/``--ow``).

    ``ow`` is omni-weight. Midjourney accepts 0-1000; validated at
    construction. 100 is loose, higher values tighten the identity match.
    """

    oref: str | None = None
    ow: int = 100

    def __post_init__(self) -> None:
        if not 0 <= self.ow <= 1000:
            raise ValueError(
                f"IdentityStack.ow must be 0-1000 per Midjourney's --ow "
                f"range; got {self.ow!r}."
            )


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

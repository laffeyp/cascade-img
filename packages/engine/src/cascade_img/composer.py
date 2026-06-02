"""Assemble Midjourney v7 prompt strings from composable prompt parts.

The consumer supplies a subject, an optional style stack, an optional
identity stack, an optional render-parameter stack, and an aspect ratio.
The composer emits the backend-specific prompt string. v0.1 emits Midjourney
v7 syntax: ``--ar``, ``--v 7``, ``--style raw``, ``--p``, ``--sref``, ``--s``,
``--oref``, ``--ow``, ``--no``, ``--tile``, ``--chaos``, ``--weird``,
``--stop``, ``--q``, ``--seed``, ``--iw``, and leading image-prompt URLs.

Every range is validated at construction (``__post_init__``) so a bad value
fails before it reaches the wire, in the same place the consumer built it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from cascade_img.vocabulary import emit


@dataclass
class Subject:
    """The thing being depicted, plus content-level prompt parts.

    ``text`` must be a non-empty, non-whitespace description; an empty subject
    would otherwise produce a leading-space, subject-less prompt that
    Midjourney renders as noise.

    ``constraints`` are folded into the prompt as comma-separated phrases
    after ``text``; Midjourney weights repeated concepts higher, so naming
    style constraints explicitly (e.g. "pixel-art sprite", "limited palette")
    pulls the render in that direction more reliably than a single phrase.

    ``negatives`` become a single ``--no a, b, c`` clause (suppress text,
    watermarks, extra limbs). They are emitted as the *last* flag so the
    bridge's per-job routing token can merge into the same ``--no`` clause
    rather than adding a second one.

    ``image_prompts`` are reference-image URLs that Midjourney requires to
    *lead* the prompt; they are emitted before the subject text. ``--iw``
    (``image_weight``, 0-3) only means anything alongside image prompts, so
    setting it without ``image_prompts`` is rejected at construction.
    """

    text: str
    constraints: list[str] = field(default_factory=list)
    negatives: list[str] = field(default_factory=list)
    image_prompts: list[str] = field(default_factory=list)
    image_weight: float | None = None

    def __post_init__(self) -> None:
        if not self.text or not self.text.strip():
            raise ValueError(
                "Subject.text must be a non-empty description; "
                "empty/whitespace subjects render as noise."
            )
        if self.image_weight is not None:
            if not any(u.strip() for u in self.image_prompts):
                raise ValueError(
                    "Subject.image_weight (--iw) is only meaningful with "
                    "image_prompts; supply at least one image URL or drop "
                    "image_weight."
                )
            if not 0 <= self.image_weight <= 3:
                raise ValueError(
                    f"Subject.image_weight must be 0-3 per Midjourney's --iw "
                    f"range; got {self.image_weight!r}."
                )


@dataclass
class StyleStack:
    """Style-related prompt parts. ``None`` values are omitted from the prompt.

    - ``moodboard`` is Midjourney's ``--p`` personalization profile code
      (e.g. ``m7458053701014388751``). The composer doesn't enforce a
      prefix convention; pass the code as-is.
    - ``sref`` is Midjourney's ``--sref`` style-reference URL or integer code.
    - ``stylize`` is Midjourney's ``--s`` value (0-1000; validated at
      construction). Default 100 if omitted at Midjourney's end.
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

    ``ow`` is omni-weight (0-1000; validated at construction). 100 is loose,
    higher values tighten the identity match.
    """

    oref: str | None = None
    ow: int = 100

    def __post_init__(self) -> None:
        if not 0 <= self.ow <= 1000:
            raise ValueError(
                f"IdentityStack.ow must be 0-1000 per Midjourney's --ow "
                f"range; got {self.ow!r}."
            )


@dataclass
class ParamStack:
    """Render-control parameters. ``None`` / ``False`` values are omitted.

    Each range is the current Midjourney v7 range, validated at construction:

    - ``tile`` toggles ``--tile`` (seamless, repeating output).
    - ``chaos`` is ``--chaos`` (0-100): grid variety.
    - ``weird`` is ``--weird`` (0-3000): offbeat aesthetics.
    - ``stop`` is ``--stop`` (10-100): halt the render early for rough drafts.
    - ``quality`` is ``--q``, one of {1, 2, 4} on v7 (GPU-cost lever; affects
      only the initial grid — the U-button upscales inherit the grid).
    - ``seed`` is ``--seed`` (0-4294967295). Reproducibility holds only within
      a fixed model + params in non-Turbo mode, and even then outputs are
      near-identical, not bit-identical. Store it as "the seed we requested".
    """

    tile: bool = False
    chaos: int | None = None
    weird: int | None = None
    stop: int | None = None
    quality: int | None = None
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.chaos is not None and not 0 <= self.chaos <= 100:
            raise ValueError(
                f"ParamStack.chaos must be 0-100 per Midjourney's --chaos "
                f"range; got {self.chaos!r}."
            )
        if self.weird is not None and not 0 <= self.weird <= 3000:
            raise ValueError(
                f"ParamStack.weird must be 0-3000 per Midjourney's --weird "
                f"range; got {self.weird!r}."
            )
        if self.stop is not None and not 10 <= self.stop <= 100:
            raise ValueError(
                f"ParamStack.stop must be 10-100 per Midjourney's --stop "
                f"range; got {self.stop!r}."
            )
        if self.quality is not None and self.quality not in (1, 2, 4):
            raise ValueError(
                f"ParamStack.quality must be one of 1, 2, 4 (Midjourney v7 "
                f"--q set); got {self.quality!r}."
            )
        if self.seed is not None and not 0 <= self.seed <= 4294967295:
            raise ValueError(
                f"ParamStack.seed must be 0-4294967295 per Midjourney's "
                f"--seed range; got {self.seed!r}."
            )


class PromptComposer:
    """Compose Midjourney v7 prompts from composable prompt parts.

    Stateless. Hold one in a module-level singleton if you want, or instantiate
    per call — there's nothing to share.
    """

    def compose(
        self,
        subject: Subject,
        style: StyleStack | None = None,
        identity: IdentityStack | None = None,
        params: ParamStack | None = None,
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

        prompt_parts_used: list[str] = []

        if style is not None:
            if style.style_raw:
                flags.append("--style raw")
            if style.moodboard:
                flags.append(f"--p {style.moodboard}")
                prompt_parts_used.append("moodboard")
            if style.sref:
                flags.append(f"--sref {style.sref}")
                prompt_parts_used.append("sref")
            if style.stylize is not None:
                flags.append(f"--s {style.stylize}")
                prompt_parts_used.append("stylize")
        else:
            flags.append("--style raw")

        if identity is not None and identity.oref:
            flags.append(f"--oref {identity.oref}")
            flags.append(f"--ow {identity.ow}")
            prompt_parts_used.extend(["oref", "ow"])

        if params is not None:
            if params.tile:
                flags.append("--tile")
                prompt_parts_used.append("tile")
            if params.chaos is not None:
                flags.append(f"--chaos {params.chaos}")
                prompt_parts_used.append("chaos")
            if params.weird is not None:
                flags.append(f"--weird {params.weird}")
                prompt_parts_used.append("weird")
            if params.stop is not None:
                flags.append(f"--stop {params.stop}")
                prompt_parts_used.append("stop")
            if params.quality is not None:
                flags.append(f"--q {params.quality}")
                prompt_parts_used.append("quality")
            if params.seed is not None:
                flags.append(f"--seed {params.seed}")
                prompt_parts_used.append("seed")

        if subject.image_weight is not None:
            flags.append(f"--iw {subject.image_weight}")
            prompt_parts_used.append("image_weight")

        # --no MUST be the final flag: the bridge's routing-token merge finds
        # a trailing "--no <list>" end-anchored and appends its needle to that
        # one clause. A --no anywhere but last would swallow later flags.
        negatives = [n.strip() for n in subject.negatives if n.strip()]
        if negatives:
            flags.append("--no " + ", ".join(negatives))
            prompt_parts_used.append("negatives")

        body = subject_text + " " + " ".join(flags)

        # Midjourney requires image-prompt URLs to lead the prompt.
        image_prompts = [u.strip() for u in subject.image_prompts if u.strip()]
        if image_prompts:
            prompt = " ".join(image_prompts) + " " + body
            prompt_parts_used.insert(0, "image_prompt")
        else:
            prompt = body

        emit(
            "PROMPT_COMPOSED",
            prompt_parts_used=prompt_parts_used,
            aspect_ratio=aspect_ratio,
            prompt_chars=len(prompt),
        )
        return prompt

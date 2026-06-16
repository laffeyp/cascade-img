"""Assemble Midjourney prompt strings from composable prompt parts.

The consumer supplies a subject, an optional style stack, an optional
identity stack, an optional render-parameter stack, an aspect ratio, and a
model ``version``. The composer emits the backend-specific prompt string.

cascade-img is **version-aware** and defaults to Midjourney **V8.1** (MJ's
default model since 2026-06-11). It also targets **V7** because V8.1 does not
support every V7 feature — most importantly Omni Reference (``--oref``/``--ow``),
cascade-img's identity lock, which is V7-only. The parameter surface is gated by
version, grounded in MJ's own Version compatibility chart
(docs.midjourney.com, updated 2026-06-11):

- **Both V7 and V8.1:** ``--ar``, ``--style raw``, ``--p``, ``--sref``,
  ``--sw``, ``--s``, ``--no``, ``--tile``, ``--exp``, ``--chaos``, ``--weird``,
  ``--seed``, ``--iw``, leading image-prompt URLs.
- **V7 only:** ``--oref``/``--ow`` (Omni Reference), ``--q`` (Quality).
- **V8.1 only:** ``--hd`` (native 2048px) / ``--sd`` (1024px) — V8.1 renders at
  native resolution without a separate upscale step.

Cross-version conflicts (e.g. ``--oref`` requested on V8.1) fail loudly at
``compose()`` rather than silently altering the render — MJ itself silently
downgrades an oref prompt to V7, which this composer refuses to do quietly.
Per-field ranges are validated at construction (``__post_init__``); the
version/feature compatibility is validated in ``compose()`` where the version
and the stacks are both in scope.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from cascade_img.vocabulary import emit

_ASPECT_RATIO_RE = re.compile(r"^\d+:\d+$")

# Accepted Midjourney model versions cascade-img composes for. "8" is accepted
# as the bare token MJ resolves to the current V8 sub-version (V8.1 as of
# 2026-06); "8.1" is explicit. Feature gating treats "8" and "8.1" identically
# (the V8 family); only "7" unlocks the V7-only features.
_SUPPORTED_VERSIONS = ("7", "8", "8.1")
_DEFAULT_VERSION = "8.1"

# Midjourney native video generation (own image -> 5s clip). Per
# docs.midjourney.com "Video" (updated 2026-06-11): a video prompt is
# ``<image_url> [text] --video`` plus ONLY the video-specific params below — any
# image params (--ar/--sref/--oref/--q/--hd/--chaos/...) are stripped by MJ when
# --video is set, so video composition is a disjoint surface from compose().
#   --motion low|high  (default low)   --raw            --loop (start==end frame)
#   --end <url>        (different end frame; mutually exclusive with --loop)
#   --bs 1|2|4         (batch size; how many videos per prompt)
# Video resolution (SD/HD) is a settings-panel toggle, NOT a prompt flag, so it
# is intentionally not composed here.
_VIDEO_MOTIONS = ("low", "high")
_VIDEO_BATCH_SIZES = (1, 2, 4)


def _reject_flag_injection(value: str, where: str) -> str:
    """Reject ``--`` inside a free-text prompt field.

    The composed prompt is a flat string, so a stray ``--no hands`` typed into a
    subject/constraint/negative would be parsed by Midjourney as a *flag*, not
    text — silently changing render parameters. Flags belong in the typed
    stacks; free text carrying ``--`` is almost certainly a misplaced flag, so
    it fails loudly at construction (the module's validate-at-construction
    contract) rather than corrupting the render."""
    if "--" in value:
        raise ValueError(
            f"{where} must not contain '--' (Midjourney would parse it as a "
            f"flag, silently altering render parameters); got {value!r}. "
            f"Pass flags through StyleStack/IdentityStack/ParamStack instead."
        )
    return value


@dataclass
class Subject:
    """The thing being depicted, plus content-level prompt parts.

    ``text`` is the non-empty description of what to depict (validated at
    construction).

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
        _reject_flag_injection(self.text, "Subject.text")
        for c in self.constraints:
            _reject_flag_injection(c, "Subject.constraints entries")
        for n in self.negatives:
            _reject_flag_injection(n, "Subject.negatives entries")
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
      (e.g. ``m`` followed by a long digit string). The composer doesn't
      enforce a prefix convention; pass the code as-is.
    - ``sref`` is Midjourney's ``--sref`` style-reference URL or integer code.
    - ``sw`` is Midjourney's ``--sw`` style weight (0-1000; default 100 at
      Midjourney's end): how strongly the ``sref`` pulls. Only meaningful with
      ``sref``, so setting it without one is rejected at construction.
    - ``stylize`` is Midjourney's ``--s`` value (0-1000; validated at
      construction). Default 100 if omitted at Midjourney's end.
    - ``style_raw`` toggles the ``--style raw`` flag that suppresses
      Midjourney's default opinion injection.
    """

    moodboard: str | None = None
    sref: str | None = None
    sw: int | None = None
    stylize: int | None = None
    style_raw: bool = True

    def __post_init__(self) -> None:
        # Normalize the free-text reference fields: strip surrounding whitespace
        # and treat a now-empty value as absent (None). Without this, a
        # whitespace-only moodboard/sref (e.g. "   " from a hand-edited registry)
        # is truthy at the compose() `if style.moodboard:` guard and emits a
        # value-less `--p` / `--sref` flag — which Midjourney silently treats as a
        # default-profile fallback or rejects, corrupting the render. Matches how
        # "" is already omitted and the module's "None values are omitted" +
        # validate-at-construction contract.
        self.moodboard = (self.moodboard or "").strip() or None
        self.sref = (self.sref or "").strip() or None
        if self.stylize is not None and not 0 <= self.stylize <= 1000:
            raise ValueError(
                f"StyleStack.stylize must be 0-1000 per Midjourney's --s "
                f"range; got {self.stylize!r}."
            )
        if self.sw is not None:
            if not (self.sref and self.sref.strip()):
                raise ValueError(
                    "StyleStack.sw (--sw) is only meaningful with a style "
                    "reference; supply sref or drop sw."
                )
            if not 0 <= self.sw <= 1000:
                raise ValueError(
                    f"StyleStack.sw must be 0-1000 per Midjourney's --sw range; got {self.sw!r}."
                )


@dataclass
class IdentityStack:
    """Omni-reference identity lock (Midjourney v7's ``--oref``/``--ow``).

    ``ow`` is omni-weight (0-1000; validated at construction). 100 is loose,
    higher values tighten the identity match.

    **V7 only.** Omni Reference is not supported on V8.1 (MJ silently falls back
    to V7 if an oref image is supplied). ``compose()`` therefore requires
    ``version='7'`` whenever ``oref`` is set, and raises otherwise rather than
    downgrading the model silently. A V8 Omni Reference is "in training" per MJ's
    2026-06-11 announcement but not yet shipped.
    """

    oref: str | None = None
    ow: int = 100

    def __post_init__(self) -> None:
        # Strip surrounding whitespace and treat a now-empty oref as absent, so a
        # whitespace-only oref is omitted rather than emitted as a value-less
        # `--oref` flag (which would also swallow the following `--ow` value).
        self.oref = (self.oref or "").strip() or None
        if not 0 <= self.ow <= 1000:
            raise ValueError(
                f"IdentityStack.ow must be 0-1000 per Midjourney's --ow range; got {self.ow!r}."
            )


@dataclass
class ParamStack:
    """Render-control parameters. ``None`` / ``False`` values are omitted.

    Each range is the current Midjourney v7 range, validated at construction:

    - ``tile`` toggles ``--tile`` (seamless, repeating output).
    - ``exp`` is ``--exp`` (0-100, whole number): v7 experimental aesthetics —
      more detail/dynamism. Values above ~25 can overwhelm ``stylize``/``p``.
    - ``chaos`` is ``--chaos`` (0-100): grid variety.
    - ``weird`` is ``--weird`` (0-3000): offbeat aesthetics.
    - ``quality`` is ``--q``, one of {1, 2, 4} (GPU-cost lever; affects only the
      initial grid — the U-button upscales inherit the grid). **V7 only** — V8.1
      does not support ``--q`` (use ``hd``/``sd`` for V8.1 resolution control).
    - ``hd`` toggles ``--hd``: V8.1 native 2048x2048 rendering, no separate
      upscale step (~1.3 GPU-min). **V8.1 only.**
    - ``sd`` toggles ``--sd``: V8.1 native 1024x1024 rendering (~0.8 GPU-min).
      **V8.1 only.** Mutually exclusive with ``hd``.
    - ``seed`` is ``--seed`` (0-4294967295). Reproducibility holds only within
      a fixed model + params in non-Turbo mode, and even then outputs are
      near-identical, not bit-identical. Store it as "the seed we requested".
    """

    tile: bool = False
    exp: int | None = None
    chaos: int | None = None
    weird: int | None = None
    quality: int | None = None
    hd: bool = False
    sd: bool = False
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.hd and self.sd:
            raise ValueError(
                "ParamStack.hd (2048px) and ParamStack.sd (1024px) are mutually "
                "exclusive; set at most one (both are V8.1-only)."
            )
        if self.exp is not None and not 0 <= self.exp <= 100:
            raise ValueError(
                f"ParamStack.exp must be 0-100 (whole number) per Midjourney's "
                f"--exp range; got {self.exp!r}."
            )
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
    """Compose Midjourney prompts from composable prompt parts.

    Version-aware: ``compose(..., version=...)`` defaults to V8.1 and accepts
    ``'7'``/``'8'``/``'8.1'``. Stateless. Hold one in a module-level singleton if
    you want, or instantiate per call — there's nothing to share.
    """

    def compose(
        self,
        subject: Subject,
        style: StyleStack | None = None,
        identity: IdentityStack | None = None,
        params: ParamStack | None = None,
        aspect_ratio: str = "1:1",
        version: str | None = None,
    ) -> str:
        """Return a Midjourney prompt string for the given model ``version``.

        ``version`` is one of ``'7'``, ``'8'``, ``'8.1'``; ``None`` (the default)
        resolves to ``_DEFAULT_VERSION`` (``'8.1'``) — the single source of truth
        for the default, so callers (the MCP tool, the registry) pass ``None``
        rather than re-hardcoding a default that could drift from this constant.
        Version-gated features fail loudly when mismatched: ``--oref``/``--ow``
        and ``--q`` require ``version='7'``; ``--hd``/``--sd`` require the V8
        family. See the module docstring for the full compatibility split."""
        # Validate here, not in a dataclass: aspect_ratio is a bare argument. A
        # typo like "16x9" or "16:9 --tile" would otherwise ride into "--ar ..."
        # and be parsed by MJ as a malformed flag (or an injected extra one).
        if not _ASPECT_RATIO_RE.fullmatch(aspect_ratio):
            raise ValueError(
                f"aspect_ratio must look like '16:9' (digits:digits); got {aspect_ratio!r}."
            )
        # Resolve the default from the single source (_DEFAULT_VERSION), then
        # normalize + validate. A typo ('v7', '7.0') must fail loudly here rather
        # than ride into "--v <typo>" and be rejected by MJ only at render time
        # (the edge case external-grammar trap).
        version = _DEFAULT_VERSION if version is None else str(version).strip()
        if version not in _SUPPORTED_VERSIONS:
            raise ValueError(
                f"version must be one of {', '.join(_SUPPORTED_VERSIONS)} "
                f"(Midjourney model version); got {version!r}. cascade-img "
                f"defaults to '{_DEFAULT_VERSION}' (MJ's current default); use "
                f"'7' for the Omni Reference (--oref) identity lock, which V8.1 "
                f"does not support."
            )
        is_v7 = version == "7"
        parts: list[str] = [subject.text.strip()]
        for c in subject.constraints:
            c = c.strip()
            if c:
                parts.append(c)
        subject_text = ", ".join(parts)

        flags: list[str] = []
        flags.append(f"--ar {aspect_ratio}")
        flags.append(f"--v {version}")

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
                if style.sw is not None:
                    flags.append(f"--sw {style.sw}")
                    prompt_parts_used.append("sw")
            if style.stylize is not None:
                flags.append(f"--s {style.stylize}")
                prompt_parts_used.append("stylize")
        else:
            flags.append("--style raw")

        if identity is not None and identity.oref:
            if not is_v7:
                raise ValueError(
                    "Omni Reference (--oref/--ow) is a Midjourney V7 feature; "
                    f"V{version} does not support it (MJ silently downgrades an "
                    "oref prompt to V7). Pass version='7' to use the identity "
                    "lock, or drop oref to render on V8.1."
                )
            flags.append(f"--oref {identity.oref}")
            flags.append(f"--ow {identity.ow}")
            prompt_parts_used.extend(["oref", "ow"])

        if params is not None:
            if params.tile:
                flags.append("--tile")
                prompt_parts_used.append("tile")
            if params.exp is not None:
                flags.append(f"--exp {params.exp}")
                prompt_parts_used.append("exp")
            if params.chaos is not None:
                flags.append(f"--chaos {params.chaos}")
                prompt_parts_used.append("chaos")
            if params.weird is not None:
                flags.append(f"--weird {params.weird}")
                prompt_parts_used.append("weird")
            if params.quality is not None:
                if not is_v7:
                    raise ValueError(
                        "--q (quality) is a Midjourney V7 parameter; "
                        f"V{version} does not support it. Pass version='7' to "
                        "use --q, or use hd/sd for V8.1 resolution control."
                    )
                flags.append(f"--q {params.quality}")
                prompt_parts_used.append("quality")
            if params.hd or params.sd:
                if is_v7:
                    raise ValueError(
                        "--hd/--sd (native-resolution rendering) are Midjourney "
                        "V8.1 parameters; V7 does not support them (V7 uses --q "
                        "plus a separate upscale). Drop hd/sd, or render on V8.1."
                    )
                if params.hd:
                    flags.append("--hd")
                    prompt_parts_used.append("hd")
                if params.sd:
                    flags.append("--sd")
                    prompt_parts_used.append("sd")
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

    def compose_video(
        self,
        image_url: str,
        text: str | None = None,
        motion: str | None = None,
        raw: bool = False,
        loop: bool = False,
        end_frame: str | None = None,
        batch_size: int | None = None,
    ) -> str:
        """Compose a Midjourney **native video** prompt (own image -> 5s clip).

        Emits ``<image_url> [text] --video`` plus only the video-specific params
        (``--motion``, ``--raw``, ``--loop``, ``--end``, ``--bs``). This is a
        disjoint surface from :meth:`compose`: MJ strips image params when
        ``--video`` is set, so none are accepted here.

        - ``image_url`` — the starting frame; required, leads the prompt.
        - ``text`` — optional motion/scene description.
        - ``motion`` — ``"low"`` (default at MJ) or ``"high"``; ``None`` omits the flag.
        - ``raw`` — ``--raw`` for tighter prompt adherence / less added motion flair.
        - ``loop`` — ``--loop``: reuse the start frame as the end frame (seamless loop).
        - ``end_frame`` — a *different* end-frame URL (``--end``). Mutually
          exclusive with ``loop`` (you cannot both reuse the start and set a new end).
        - ``batch_size`` — ``--bs`` (1, 2, or 4); how many videos to generate.

        Per the validate-at-composition contract, conflicts fail loudly here
        rather than at the wire. (V-1 scope: composition only — firing native
        video through the bridge + its signal vocabulary lands in V-2.)
        """
        if not image_url or not image_url.strip():
            raise ValueError(
                "compose_video requires a starting-frame image_url (a video is "
                "generated FROM an image); got empty."
            )
        image_url = _reject_flag_injection(image_url.strip(), "compose_video image_url")
        if motion is not None and motion not in _VIDEO_MOTIONS:
            raise ValueError(
                f"motion must be one of {_VIDEO_MOTIONS} (Midjourney --motion); got {motion!r}."
            )
        if loop and end_frame is not None and end_frame.strip():
            raise ValueError(
                "loop and end_frame are mutually exclusive: --loop reuses the "
                "start frame as the end frame, while --end sets a different end "
                "frame. Pick one."
            )
        if batch_size is not None and batch_size not in _VIDEO_BATCH_SIZES:
            raise ValueError(
                f"batch_size must be one of {_VIDEO_BATCH_SIZES} (Midjourney --bs); "
                f"got {batch_size!r}."
            )

        parts: list[str] = [image_url]
        if text and text.strip():
            parts.append(_reject_flag_injection(text.strip(), "compose_video text"))
        parts.append("--video")
        if motion is not None:
            parts.append(f"--motion {motion}")
        if raw:
            parts.append("--raw")
        if loop:
            parts.append("--loop")
        if end_frame and end_frame.strip():
            end_url = _reject_flag_injection(end_frame.strip(), "compose_video end_frame")
            parts.append(f"--end {end_url}")
        if batch_size is not None:
            parts.append(f"--bs {batch_size}")
        return " ".join(parts)

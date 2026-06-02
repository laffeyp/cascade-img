"""cascade-img — LLM-operable image-generation pipeline.

v0.1.0. Midjourney via Discord ships in this release; pluggable backends
(Flux, DALL-E, Imagen) follow at v0.2+.
"""

__version__ = "0.1.0"

from cascade_img.backends.base import BackendCapabilities, ImageGenerationBackend
from cascade_img.backends.midjourney_discord import (
    MIDJOURNEY_DISCORD_CAPABILITIES,
    Config,
    MidjourneyDiscordBackend,
    MissingEnvError,
)
from cascade_img.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.curation import (
    DEFAULT_TOLERANCE,
    QUADRANT_OFFSETS,
    alpha_key_corners,
    auto_trim,
    contact_sheet,
    crop_quadrant,
    palette_quantize,
    promote,
    score_grid,
    sprite_sheet,
)
from cascade_img.log import AgentDecision, PromptLog
from cascade_img.vocabulary import (
    VOCAB_VERSION,
    Emitter,
    Signal,
    Vocabulary,
    assert_no_signal,
    assert_signal,
    capture,
    clear,
    emit,
    flush_to_file,
    format_for_ai,
    snapshot,
    vocabulary,
)

__all__ = [  # noqa: RUF022 — order is by concern, not alphabetical
    "__version__",
    # backends
    "BackendCapabilities",
    "ImageGenerationBackend",
    "MidjourneyDiscordBackend",
    "MIDJOURNEY_DISCORD_CAPABILITIES",
    "Config",
    "MissingEnvError",
    # composer
    "PromptComposer",
    "Subject",
    "StyleStack",
    "IdentityStack",
    "ParamStack",
    # curation
    "crop_quadrant",
    "alpha_key_corners",
    "promote",
    "contact_sheet",
    "auto_trim",
    "palette_quantize",
    "sprite_sheet",
    "score_grid",
    "QUADRANT_OFFSETS",
    "DEFAULT_TOLERANCE",
    # log
    "PromptLog",
    "AgentDecision",
    # instrumentation
    "emit",
    "snapshot",
    "clear",
    "flush_to_file",
    "format_for_ai",
    "assert_signal",
    "assert_no_signal",
    "capture",
    "vocabulary",
    "Emitter",
    "Vocabulary",
    "Signal",
    "VOCAB_VERSION",
]

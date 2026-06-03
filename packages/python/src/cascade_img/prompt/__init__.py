"""Prompt domain — building the backend prompt string and recording each roll.

* :mod:`.composer` turns composable parts (subject, style reference, identity
  reference, params, aspect ratio) into a Midjourney v7 prompt string. Pure;
  no I/O.
* :mod:`.log` is :class:`PromptLog`, the append-only JSONL ledger that doubles
  as the agent's working memory across loop iterations.

Both deal only in prompts and both emit through :mod:`cascade_img.vocabulary`,
which is why they live together here rather than loose at the package root.
"""

from cascade_img.prompt.composer import (
    IdentityStack,
    ParamStack,
    PromptComposer,
    StyleStack,
    Subject,
)
from cascade_img.prompt.prompt_log import AgentDecision, PromptLog

__all__ = [
    "AgentDecision",
    "IdentityStack",
    "ParamStack",
    "PromptComposer",
    "PromptLog",
    "StyleStack",
    "Subject",
]

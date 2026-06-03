"""The cascade-img MCP tool surface, one module per concern.

* :mod:`.prompt_tools` — compose a prompt.
* :mod:`.generation_tools` — fire and track a generation against the bridge.
* :mod:`.curation_tools` — crop, key, trim, quantize, sheet, score, promote.
* :mod:`.log_tools` — append to and read the prompt log.

``tool_server`` imports :data:`ALL_TOOLS` and registers each on the FastMCP
instance; the function's ``__name__`` becomes the MCP tool name and its
docstring becomes the tool description.
"""

from cascade_img.interfaces.mcp.tools.curation_tools import (
    alpha_key,
    auto_trim,
    contact_sheet,
    crop_grid,
    palette_quantize,
    promote,
    score_grid,
    sprite_sheet,
)
from cascade_img.interfaces.mcp.tools.generation_tools import (
    bridge_health,
    imagine,
    mj_action,
    status,
    wait,
)
from cascade_img.interfaces.mcp.tools.log_tools import log_append, read_prompt_log
from cascade_img.interfaces.mcp.tools.prompt_tools import compose_prompt

# Registration order = the order tools are advertised over MCP. Grouped by
# concern: prompt -> generation -> curation -> log.
ALL_TOOLS = (
    compose_prompt,
    imagine,
    wait,
    status,
    bridge_health,
    mj_action,
    crop_grid,
    alpha_key,
    promote,
    contact_sheet,
    auto_trim,
    palette_quantize,
    sprite_sheet,
    score_grid,
    log_append,
    read_prompt_log,
)

__all__ = [
    "ALL_TOOLS",
    "alpha_key",
    "auto_trim",
    "bridge_health",
    "compose_prompt",
    "contact_sheet",
    "crop_grid",
    "imagine",
    "log_append",
    "mj_action",
    "palette_quantize",
    "promote",
    "read_prompt_log",
    "score_grid",
    "sprite_sheet",
    "status",
    "wait",
]

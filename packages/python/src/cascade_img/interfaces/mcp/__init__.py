"""The ``cascade-mcp`` MCP server — the agent-facing interface.

* :mod:`.tool_server` builds the FastMCP instance, registers the tools, and
  owns the ``cascade-mcp`` entry point (stdio by default, ``--http`` for SSE).
* :mod:`._envelope` holds the response envelope (:func:`._envelope._run_tool`)
  and the long-lived backend/composer/log singletons.
* :mod:`.tools` is the tool surface, one module per concern.
"""

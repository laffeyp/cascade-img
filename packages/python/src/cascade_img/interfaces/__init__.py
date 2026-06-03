"""Interfaces — the surfaces external actors drive cascade-img through.

Both speak to the same backend; they differ only in who calls them.

* :mod:`.mcp` — the ``cascade-mcp`` MCP server (:mod:`.mcp.tool_server`), the
  agent-facing surface (Claude Desktop, Cursor, Cline, …).
* :mod:`.cli` — the ``cascade-mj`` console script (:mod:`.cli.generate_image`)
  for humans and scripts.

The bridge daemon (``cascade-mj-bridge``) is not an interface in this sense; it
lives with the backend it serves under
:mod:`cascade_img.backends.midjourney_discord`.
"""

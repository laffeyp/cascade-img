"""Console-script CLIs for cascade-img.

* ``cascade_img.cli.mj`` — ``cascade-mj``: the unified roll-and-log command.
  Takes an asset_id, looks up its facets in a registry file, composes the
  prompt via :class:`cascade_img.composer.PromptComposer`, fires it at the
  running bridge, waits for the result, and appends to the prompt log.

The other console scripts live next to the modules they wrap
(:func:`cascade_img.backends.midjourney_discord.bridge.main` for
``cascade-mj-bridge``, :func:`cascade_img.mcp_server.main` for
``cascade-mcp``).
"""

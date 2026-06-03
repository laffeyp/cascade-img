"""Console-script CLI for cascade-img.

* :mod:`cascade_img.interfaces.cli.generate_image` — ``cascade-mj``: takes an
  asset_id, looks up its prompt parts in a registry file
  (:mod:`.asset_registry`), composes the prompt via
  :class:`cascade_img.prompt.composer.PromptComposer`, fires it at the running
  bridge daemon, waits for the result, and writes a record to the prompt log.

The other console scripts live next to the modules they wrap
(:func:`cascade_img.backends.midjourney_discord.bridge.main` for
``cascade-mj-bridge``, :func:`cascade_img.interfaces.mcp.tool_server.main` for
``cascade-mcp``).
"""

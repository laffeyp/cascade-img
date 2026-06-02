"""Console-script CLIs for cascade-img.

* ``cascade_img.cli.mj`` — ``cascade-mj``: takes an asset_id, looks up its
  prompt parts in a registry file, composes the prompt via
  :class:`cascade_img.composer.PromptComposer`, fires it at the running
  bridge daemon, waits for the result, and writes a record to the prompt log.

The other console scripts live next to the modules they wrap
(:func:`cascade_img.backends.midjourney_discord.bridge.main` for
``cascade-mj-bridge``, :func:`cascade_img.mcp_server.main` for
``cascade-mcp``).
"""

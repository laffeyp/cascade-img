# `_archive/`

Code and material that pre-dates the cascade-img package extraction or that has been superseded by a current module. Kept for provenance — these files are NOT part of the published distribution (excluded from sdist and wheel via `pyproject.toml`) and are NOT importable from the `cascade_img` package.

If you need the live equivalents:

| archived | live replacement |
|---|---|
| `_archive/legacy/midjourney_discord_client.py` | `cascade_img.backends.midjourney_discord.MidjourneyDiscordBackend` — same surface (`imagine` / `wait`), conforming to `ImageGenerationBackend`. |

The archive is read-only relative to the published package: no code in `cascade_img/` imports from here. Refer back when you need the history of how a module looked before it was generalized.

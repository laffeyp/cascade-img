# Terms of Service Context

cascade-img drives Midjourney through a Discord user account using `discord.py-self`. This is:

- Automation of a Discord account, which Discord's [Terms of Service](https://discord.com/terms) prohibit.
- Automation of Midjourney, which Midjourney's [Terms of Service](https://docs.midjourney.com/docs/terms-of-service) prohibit.

Midjourney has no public API. Its [Enterprise API](https://www.midjourney.com/) exists but is application-only and inaccessible to individual developers. The OSS pattern for programmatic Midjourney access is driving a user account via the Discord bot APIs — this is how every open-source Midjourney tool today works. Paid third-party REST proxies (TheNextLeg, PIAPI, useapi.net, GoAPI) run the same mechanism behind a hosted facade.

## Pluggable backend

The `ImageGenerationBackend` interface in `cascade_img.backends.base` is the extension point: when the Flux-via-Fal backend ships in v0.3, the same composer, curation kit, MCP server, and CLI drive it without consumer code changes. Planned backends:

- Flux Pro / Dev / Schnell via Fal — v0.3
- OpenAI `gpt-image-1` / DALL-E 3 — v0.3
- Stable Diffusion 3.5 via Stability — v0.4
- Flux Kontext (instruction-edit) — v0.4
- Imagen 3 via Vertex — v0.5
- Ideogram, Recraft V3 — v0.5

When Midjourney's Enterprise API becomes generally available, an official backend replaces the self-bot path.

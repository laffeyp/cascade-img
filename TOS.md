# Terms of Service Posture

Cascade-img drives Midjourney through a Discord user account using `discord.py-self`. This is:

- **Automation of a Discord account**, which Discord's [Terms of Service](https://discord.com/terms) prohibit.
- **Automation of Midjourney**, which Midjourney's [Terms of Service](https://docs.midjourney.com/docs/terms-of-service) prohibit.

**Accounts get banned.** Use a sacrificial Discord account.

This is the only OSS path to programmatic Midjourney access as of this release. Midjourney's [Enterprise API](https://www.midjourney.com/) exists but is application-only and inaccessible to individual developers. Paid third-party REST proxies (TheNextLeg, PIAPI, useapi.net, GoAPI) shift the ToS exposure onto their account pools but do not eliminate it — they run the same self-bot mechanism on accounts they own, charge $20-$50/month, and vendor-lock prompts through their infrastructure.

This software is published for **research, prototyping, and personal use**, not production deployments.

## The pluggable-backend escape

Cascade-img's architecture exists in part to give users a sanctioned alternative. The `ImageGenerationBackend` interface in `cascade_img.backends.base` is the seam: when v0.2 ships the Flux-via-Fal backend, the same composer, curation kit, MCP server, and CLI will drive it without consumer code changes. If the legal exposure of the MJ backend matters to you, wait for the v0.2 sanctioned-API backends:

- Flux Pro / Dev / Schnell via Fal — v0.2 target
- OpenAI `gpt-image-1` / DALL-E 3 — v0.2 target
- Stable Diffusion 3.5 via Stability — v0.3 target
- Flux Kontext (instruction-edit) — v0.3 target
- Imagen 3 via Vertex — v0.4 target
- Ideogram, Recraft V3 — v0.4 target

When Midjourney's Enterprise API becomes generally available, an official `MidjourneyOfficialBackend` replaces the self-bot backend.

## If your account gets banned

Get a fresh Discord account, capture new credentials, plug them into `.env`, keep going. The cycle has been operationally validated; it's the cost of riding an unsanctioned channel.

---

This stance is linked from the README's first paragraph, the PyPI long description, and `OPERATIONS.md`. It is not buried.

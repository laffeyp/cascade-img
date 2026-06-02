# cascade-img

**An LLM-operable image-generation pipeline.** Midjourney via Discord today, Flux / DALL-E / Imagen / others through the same interface tomorrow. Composable V7 facets (`--p`, `--sref`, `--oref`, `--ow`) as first-class inputs, a curation toolkit (grid crop / four-corner alpha key / promote), a working-memory prompt log, and an MCP server that lets Claude Desktop, Cursor, Cline, or any MCP-aware host drive the full generate-curate-refine-promote-log loop without a human in the room for every roll.

> **ToS notice.** This drives Midjourney through a Discord user account using `discord.py-self`. Both Discord and Midjourney prohibit this. Use a sacrificial Discord account. See [TOS.md](./TOS.md).

Published by [Green Rose Systems](https://greenrosesystems.com).

---

## 60-second quickstart for an MCP-aware agent host

Drop this in your Claude Desktop, Cursor, or Cline MCP config:

```json
{
  "mcpServers": {
    "cascade-img": {
      "command": "cascade-mcp"
    }
  }
}
```

After installing the package and starting the bridge daemon (see below), ask your agent to generate a sprite. The agent gets ten tools — `compose_prompt`, `imagine`, `wait`, `status`, `bridge_health`, `crop_grid`, `alpha_key`, `promote`, `log_append`, `read_prompt_log` — with JSON schemas it can introspect. [AGENTS.md](./AGENTS.md) is the operator's guide an agent reads once.

## 60-second quickstart for a human

```bash
pip install cascade-img
cp $(python -c "import cascade_img; print(cascade_img.__path__[0])")/backends/midjourney_discord/.env.example .env
# Fill in DISCORD_USER_TOKEN, MJ_CHANNEL_ID, MJ_GUILD_ID, MJ_IMAGINE_VERSION
# See OPERATIONS.md for the capture procedure.

cascade-mj-bridge --check-env --pretty       # validate config
cascade-mj-bridge                            # start the daemon (long-running)
```

Then in another shell:

```bash
echo '{
  "bird": {
    "subject": "pixel-art sprite of a small finch, side view",
    "constraints": ["transparent background"],
    "moodboard": "m7458053701014388751",
    "sref": "https://cdn.midjourney.com/.../0_0.png",
    "aspect_ratio": "1:1"
  }
}' > assets.json

cascade-mj bird --registry assets.json --upscale all --pretty
```

JSON to stdout, exit 0 on `done`.

---

## What makes this different

V7 facet composition — `--p` (moodboard), `--sref` (style reference), `--oref` (omni-reference identity lock), `--ow` (omni-weight) — as independently stackable, typed inputs:

```python
from cascade_img.composer import PromptComposer, Subject, StyleStack, IdentityStack

prompt = PromptComposer().compose(
    Subject(
        text="the same finch with its wings raised UP in a full upstroke",
        constraints=["SIDE VIEW facing LEFT (matching the reference orientation)",
                     "low-resolution 2D game sprite", "limited palette",
                     "handmade restrained sprite art", "transparent background"],
    ),
    style=StyleStack(moodboard="m7458053701014388751", sref="https://cdn.../sref.png"),
    identity=IdentityStack(oref="https://cdn.../canonical-bird.png", ow=1000),
    aspect_ratio="1:1",
)
```

No other OSS tool treats V7 facets as composable inputs. Paid REST proxies (TheNextLeg, PIAPI, useapi.net) pass raw prompt strings through. Self-bot drivers (`erictik/midjourney-api`, `novicezk/midjourney-proxy`) drive `/imagine` but don't compose. cascade-img sits one layer up — composition, curation, reproducibility — exactly where the unoccupied ground is.

| | cascade-img | erictik/midjourney-api | novicezk/midjourney-proxy | Paid REST proxies | Sanctioned alternatives |
|---|---|---|---|---|---|
| Drives MJ V7 | yes | partial | OSS no, paid fork yes | yes | n/a |
| V7 facet composition (oref/ow as first-class) | yes | no | no | passes raw strings | n/a |
| Local HTTP bridge | yes | no (library only) | yes (Java) | n/a (hosted) | n/a (hosted) |
| Curation utilities (grid split, alpha key, promote) | yes | no | no | no | no |
| Append-only prompt log | yes | no | no | no | no |
| MCP server | yes | no | no | no | no |
| `AGENTS.md` + prompt templates | yes | no | no | no | no |
| Structured-error remediation | yes | no | no | partial | varies |
| Pluggable backend | yes (v0.1 MJ, v0.2+ Flux/DALL-E/Imagen) | MJ only | MJ only | provider-locked | single backend |
| ToS posture | self-bot, explicit and honest | self-bot, mentioned | self-bot, mentioned | self-bot, hidden | sanctioned |
| License | MIT | MIT | Apache 2.0 | proprietary | proprietary |

---

## Three console scripts

- **`cascade-mj-bridge`** — the MJ-via-Discord daemon. Run once per session.
  - `--check-env` — JSON config validation with structured remediation.
  - `--doctor` — full pre-flight (env + Discord reachability + MCP server + discord.py-self imports).
- **`cascade-mcp`** — MCP server. Stdio by default (Claude Desktop / Cursor / Cline); `--http <port>` for hosts that prefer HTTP.
- **`cascade-mj`** — unified roll-and-log CLI. Takes an `asset_id` and a registry, fires, waits, logs.

All three emit structured JSON; all three follow the same `{ok, result | error: {code, remediation}}` envelope.

---

## Signal-Driven Development

Every load-bearing state transition emits a structured signal — config validated, Discord connected, imagine fired, grid matched (with `match_path` distinguishing the patched MJ V7 fallback path), upscale received, job completed, job failed (with stable error codes for every known Discord failure mode). The vocabulary is locked at [`cascade_img/signals/versions/0.1.json`](./packages/engine/src/cascade_img/signals/versions/0.1.json). The parity tool asserts every `emit()` callsite references a vocabulary tag; the discipline ladder ships green.

```
$ pytest packages/engine/tests/ -q
... 48 passed in 0.5s
```

Read the [`packages/engine/tests/`](./packages/engine/tests/) directory to understand the daemon's contract — the tests are the contract.

---

## Documentation

- **[OPERATIONS.md](./OPERATIONS.md)** — install, env capture, the bring-up ladder, every known failure mode with structured-error code + remediation.
- **[AGENTS.md](./AGENTS.md)** — the LLM operator's guide. Read this when handing cascade-img to an agent.
- **[TOS.md](./TOS.md)** — the honest self-bot posture and the sanctioned-backend escape path.
- **[prompts/](./prompts/)** — four bundled system-prompt templates: sprite-set, character-locked variants, region backdrop, refine existing.
- **[docs/](./docs/)** — canonical product spec, packaging plan, extraction plan.

## Roadmap

| version | headline |
|---|---|
| v0.1 (current) | MJ V7 backend, facet composer, curation, MCP server, AGENTS.md, prompt templates, Python package. **Python-only** — TypeScript wrapper is a v0.2 deliverable (the `@greenrosesystems/cascade-img` placeholder on npm reserves the name). |
| v0.2 | TypeScript wrapper (BridgeClient + PromptComposer + Zod types + Node-native MCP server), Flux via Fal + OpenAI `gpt-image-1` backends, Windows bridge |
| v0.3 | Flux Kontext (instruction-edit), bundled-binary install path |
| v0.4 | Imagen, Ideogram, Recraft backends |
| v1.0 | API stable across two minor releases, three backends in production |

### v0.1.0 release checklist (operator-side)

- [ ] PyPI Trusted Publishing configured for the `greenrosesystems/cascade-img` repo against PyPI project `cascade-img` (PyPI → cascade-img project → Settings → Publishing → add GitHub publisher with workflow `release.yml`, environment empty).
- [ ] npm scope `@greenrosesystems` has a valid automation token in GitHub Actions secrets (only if/when the TS wrapper publishes; not needed for v0.1.0).
- [ ] GitHub org `greenrosesystems` has actions enabled with workflow write scope (already exercised by Sprint 003's CI workflows).
- [ ] One live-fire roll captured per `OPERATIONS.md` against the operator's `.env` (Sprint 004 recorded one such roll in the project tree; re-run on the operator's actual machine before tagging v0.1.0).

The HTTP contract between bridge and client is the load-bearing stability seam. Breaking changes there bump minor for both packages in the same release.

## License

MIT. See [LICENSE](./LICENSE).

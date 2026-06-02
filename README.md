# cascade-img

[![PyPI](https://img.shields.io/pypi/v/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![Python](https://img.shields.io/pypi/pyversions/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![CI](https://github.com/greenrosesystems/cascade-img/actions/workflows/ci.yml/badge.svg)](https://github.com/greenrosesystems/cascade-img/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)

An image-generation pipeline an LLM can drive. It runs Midjourney through Discord today; Flux, DALL-E, and Imagen will use the same interface later.

The Midjourney prompt is split into composable parts you set independently — subject, moodboard (`--p`), style reference (`--sref`), identity reference (`--oref`) and its weight (`--ow`), aspect ratio. A curation kit crops the 2×2 grid into quadrants and, optionally, removes a uniform background. A JSONL prompt log records every attempt so the next iteration knows what's been tried. An MCP server exposes all of this to Claude Desktop, Cursor, Cline, or any MCP-aware host — so an agent can compose, generate, curate, and log without a human on every attempt.

> **Context.** Midjourney has no public API. Driving it through a Discord user account is the established OSS pattern for programmatic access. Both Discord and Midjourney's Terms of Service prohibit user-account automation. See [TOS.md](./TOS.md).

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
cp "$(python -c 'import cascade_img, pathlib; print(pathlib.Path(cascade_img.__path__[0]) / ".env.example")')" .env
# Fill in DISCORD_USER_TOKEN, MJ_CHANNEL_ID, MJ_GUILD_ID, MJ_IMAGINE_VERSION
# See RUNBOOK.md for the capture procedure.

cascade-mj-bridge --check-env --pretty       # validate config
cascade-mj-bridge                            # start the daemon (long-running)

# Recommended: run the test suite from a clone before relying on a release.
# 113/113 green confirms the daemon's vocabulary contract holds end-to-end.
pytest packages/engine/tests/ -v

# For a live end-to-end check against real MJ, including the bridge boot,
# the MCP server, and every tool — see tools/smoke_mcp_walk.py:
python3 packages/engine/tools/smoke_mcp_walk.py --env-file .env
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

## How this differs

cascade-img adds a layer above the Midjourney bridge: it composes the prompt from named parts, curates the output, and records each attempt so the loop can iterate.

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

Compared to other OSS Midjourney drivers:

| | cascade-img | erictik/midjourney-api | novicezk/midjourney-proxy | Paid REST proxies |
|---|---|---|---|---|
| Drives MJ V7 | yes | partial | OSS no, paid fork yes | yes |
| Composable prompt parts (moodboard, sref, oref, ow as named inputs) | yes | no | no | passes raw strings |
| Local HTTP bridge | yes | no (library only) | yes (Java) | n/a (hosted) |
| Curation kit (grid crop, alpha key, promote) | yes | no | no | no |
| Append-only prompt log | yes | no | no | no |
| MCP server | yes | no | no | no |
| Structured-error envelope with stable codes | yes | no | no | partial |
| Pluggable backend (Flux / DALL-E / Imagen on the same interface in v0.2+) | yes | MJ only | MJ only | provider-locked |
| License | MIT | MIT | Apache 2.0 | proprietary |

---

## Three console scripts

- **`cascade-mj-bridge`** — the MJ-via-Discord daemon. Run once per session.
  - `--check-env` — JSON config validation with structured remediation.
  - `--doctor` — full pre-flight (env + Discord reachability + MCP server + discord.py-self imports).
- **`cascade-mcp`** — MCP server. Stdio by default (Claude Desktop / Cursor / Cline); `--http <port>` for hosts that prefer HTTP.
- **`cascade-mj`** — the CLI. Takes an `asset_id` and a registry, composes the prompt, fires, waits for the result, and writes a record to the prompt log.

All three emit structured JSON; all three follow the same `{ok, result | error: {code, remediation}}` envelope.

---

## Structured runtime events

Every important state change emits a structured event: config validated; Discord connected, disconnected, reconnecting; imagine fired; submit timed out (the job stays in `PENDING_GRID`, it is not failed); grid matched (with `match_path` recording which match path fired); output-path collision; upscale per-slot press failed; upscale received; job completed; job failed. Failures carry a stable error code for every known Discord failure mode.

The vocabulary is locked at [`cascade_img/vocabulary/versions/0.1.json`](./packages/engine/src/cascade_img/vocabulary/versions/0.1.json). A parity check confirms every `emit()` callsite uses a declared tag, and the full test suite passes.

```
$ pytest packages/engine/tests/ -q
... 113 passed in 0.9s
```

Read the [`packages/engine/tests/`](./packages/engine/tests/) directory to understand the daemon's contract — the tests are the contract.

---

## Documentation

- **[RUNBOOK.md](./RUNBOOK.md)** — install, env capture, the setup procedure, the reconnect lifecycle, and every known failure mode with its structured error code and remediation.
- **[AGENTS.md](./AGENTS.md)** — the LLM operator's guide. Read this when handing cascade-img to an agent.
- **[TOS.md](./TOS.md)** — the technical context: Midjourney has no public API; Discord user-account automation is the established OSS pattern; both Discord's and Midjourney's Terms of Service prohibit it.
- **[examples/demo/](./examples/demo/)** — one consumer project's worked usage of cascade-img (the demo sprite-art pipeline). Not generic templates; an example of how a real project structured agent prompts against the tool. Read AGENTS.md before any of these.

## Repository layout

```
cascade-img/
├── packages/engine/        # the Python package (import name: cascade_img) — the product
│   ├── src/cascade_img/     #   composer, vocabulary, backends/, curation/, log, mcp_server, cli/
│   ├── tests/               #   behavior-contract tests
│   └── tools/               #   vocabulary parity check, live smoke walk
├── packages/client/        # npm name reservation for the v0.2 TypeScript wrapper (placeholder)
├── examples/demo/      # one consumer project's worked usage (not generic templates)
├── vocabulary/0.1.json     # byte-identical mirror of the package's locked event catalog
├── reviews/                # internal code/documentation review reports (audit trail)
├── _archive/               # build-process history; not part of the published package
└── *.md                    # README, ARCHITECTURE, RUNBOOK, AGENTS, RUNDOWN, SECURITY, SUPPORT, …
```

The product is `packages/engine`. Everything an operator or agent needs is the
top-level Markdown plus that package; `_archive/` and `reviews/` are history,
not documentation.

## Roadmap

| version | headline |
|---|---|
| v0.1 (current) | MJ V7 backend, facet composer, curation kit (crop + flood-fill alpha key + promote), MCP server, AGENTS.md, prompt templates, Python package. **Python-only** — TypeScript wrapper is a v0.2 deliverable (the `@greenrosesystems/cascade-img` placeholder on npm reserves the name). |
| v0.2 | TypeScript wrapper (BridgeClient + PromptComposer + Zod types + Node-native MCP server), Flux via Fal + OpenAI `gpt-image-1` backends, Windows bridge |
| v0.3 | Flux Kontext (instruction-edit), bundled-binary install path |
| v0.4 | Imagen, Ideogram, Recraft backends |
| v1.0 | API stable across two minor releases, three backends in production |

The HTTP contract between the bridge and the client is the main seam between the two packages; changes there are coordinated across both.

## License

MIT. See [LICENSE](./LICENSE).

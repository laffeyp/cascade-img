# cascade-img

[![PyPI](https://img.shields.io/pypi/v/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![Python](https://img.shields.io/pypi/pyversions/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![CI](https://github.com/greenrosesystems/cascade-img/actions/workflows/ci.yml/badge.svg)](https://github.com/greenrosesystems/cascade-img/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

An image-generation pipeline an LLM can drive. It runs Midjourney through Discord today; Flux, DALL-E, and Imagen will use the same interface later.

The Midjourney prompt is split into composable parts you set independently — subject, moodboard (`--p`), style reference (`--sref`), identity reference (`--oref`) and its weight (`--ow`), aspect ratio. A curation kit crops the 2×2 grid into quadrants and, optionally, removes a uniform background. A JSONL prompt log records every attempt so the next iteration knows what's been tried. An MCP server exposes all of this to Claude Desktop, Cursor, Cline, or any MCP-aware host — so an agent can compose, generate, curate, and log without a human on every attempt.

> **The point: an agent runs the loop.** cascade-img's headline mode is letting an LLM agent drive the whole loop over the MCP tools — compose → generate → wait → inspect → curate → log, iterating on its own prompt log without a human on every roll. The CLI and Python API are conveniences for scripting and embedding; the agent loop is why the package exists. [AGENTS.md](./AGENTS.md) is the operator's guide.


Midjourney comes first by design. Midjourney has no public API, so driving it through a Discord user account is the established, accepted OSS pattern for programmatic access — and the existing tools that do this are sparsely maintained, which is what cascade-img sets out to improve on with a best-in-class take on that pattern. It is tackled first precisely because, lacking an API, it is the hardest of the image providers to integrate; with that done, adding the rest (Flux, DALL-E, Imagen) is the easier work.

> **Context.** Midjourney has no public API. Driving it through a Discord user account is the established OSS pattern for programmatic access. Both Discord and Midjourney's Terms of Service prohibit user-account automation. See [TOS.md](./TOS.md).

Published by [Green Rose Systems](https://greenrosesystems.com).

---

## Why this exists

cascade-img grew out of building a sprite-based 2D game that needed a lot of art. Midjourney could produce it, but the work that mattered was the iteration loop: try a direction, look at it, decide what to change, go again, until the result matches what you're after. Done by hand through Discord — one prompt, one click, one download at a time — that loop is slow.

Most of that loop is mechanical: compose the prompt from reusable parts, fire it, wait, crop and curate the result, write down what was tried. That part can be handed to an LLM agent, while the person still makes the judgment calls about what's right. No existing open-source Midjourney driver let an agent run the loop end to end, so the missing layer got built — first for the one game's pipeline, then generalized into this package.

The style-specific lessons (holding a non-photoreal look, locking a subject's identity across rolls) are still in the [RUNBOOK](./RUNBOOK.md) because they're useful, but nothing in the tool assumes you're making sprites.

---

## Quickstart

**Prerequisites.** A Midjourney subscription and a Discord account that can run
`/imagine` in a channel where the Midjourney bot is present, plus Python 3.14
(the current stable release — cascade-img targets the latest stable Python).
cascade-img drives *your own* Midjourney account through Discord and runs
locally on your machine.

### 1. Install

```bash
pip install cascade-img
```

This puts three console scripts on your `PATH`: `cascade-mj-bridge` (the daemon),
`cascade-mcp` (the MCP server), and `cascade-mj` (the CLI).

### 2. Configure (one-time)

cascade-img reaches Midjourney through your Discord account. Three values are
required:

- a Discord user token
- your MJ channel ID
- the current `/imagine` command version

plus your server (guild) ID whenever the channel lives in a Discord server
(almost always). These are captured from the Discord desktop app's DevTools.
**[RUNBOOK.md](./RUNBOOK.md) is the step-by-step guide**: enabling DevTools, the
token-capture snippet, and what each value means.

```bash
# Copy the env template into your working directory, then fill it in per RUNBOOK.md:
cp "$(python -c 'import cascade_img, pathlib; print(pathlib.Path(cascade_img.__path__[0]) / ".env.example")')" .env

cascade-mj-bridge --check-env --pretty   # validates the .env and names anything missing
```

### 3. Start the bridge daemon

```bash
cascade-mj-bridge          # long-running; the only process that talks to Discord
```

Leave it running. Both front doors below connect to it over local HTTP.

### 4a. Drive it from an MCP host (Claude Desktop, Cursor, Cline)

Drop this into your host's MCP config:

```json
{
  "mcpServers": {
    "cascade-img": {
      "command": "cascade-mcp"
    }
  }
}
```

Your agent gets sixteen tools with introspectable JSON schemas:

- **generation** — `imagine`, `wait`, `status`, `bridge_health`, `mj_action`
- **composition** — `compose_prompt`
- **curation** — `crop_grid`, `alpha_key`, `auto_trim`, `palette_quantize`, `contact_sheet`, `sprite_sheet`, `score_grid`, `promote`
- **working memory** — `log_append`, `read_prompt_log`

[AGENTS.md](./AGENTS.md) is the operator's guide an agent reads once.

### 4b. Drive it from the CLI

In another shell, define an asset registry (`asset_id` → prompt parts) and roll
it. Only `subject` is required; `moodboard` (a Midjourney moodboard code) and
`sref` (a style-reference image URL) are optional style controls you'd set up in
Midjourney first — omit them for a plain prompt:

```bash
echo '{
  "mountain-icon": {
    "subject": "a flat-design icon of a mountain, centered, simple shapes",
    "aspect_ratio": "1:1"
  }
}' > assets.json

cascade-mj mountain-icon --registry assets.json --upscale all --pretty
```

JSON to stdout, exit 0 on `done`; generated images land in `./generated`.

> **Verify a release before relying on it.** From a clone:
> `pytest packages/python/tests/` runs the offline suite, and
> `python3 packages/python/tools/smoke_mcp_walk.py --env-file .env` runs a live
> end-to-end check (boots the bridge and MCP server, exercises every tool).

---

## How this differs

Most Midjourney tools just pass your prompt through and hand back the image. cascade-img does the work around that: it builds the prompt from reusable named parts, crops and cleans up the result, and keeps a record of every attempt so each round can build on the last.

```python
from cascade_img.prompt.composer import PromptComposer, Subject, StyleStack, IdentityStack

prompt = PromptComposer().compose(
    Subject(
        text="a flat-design icon of a mountain",
        constraints=["centered", "simple shapes", "transparent background"],
    ),
    # Style and identity are optional. moodboard is a Midjourney moodboard code
    # and sref/oref are reference-image URLs — set them up in Midjourney first.
    style=StyleStack(moodboard="<your-moodboard-code>", sref="https://cdn.../style.png"),
    identity=IdentityStack(oref="https://cdn.../reference.png", ow=1000),
    aspect_ratio="1:1",
)
```

Compared to other OSS Midjourney drivers:

| | cascade-img | erictik/midjourney-api | novicezk/midjourney-proxy | Paid REST proxies |
|---|---|---|---|---|
| Drives MJ V7 | yes | raw passthrough (no v7 awareness) | OSS no, paid fork yes | yes |
| Composable prompt parts (moodboard, sref, oref, ow as named inputs) | yes | no | no | passes raw strings |
| Local HTTP bridge | yes | no (library only) | yes (Java) | n/a (hosted) |
| Curation kit (grid crop, alpha key, promote) | yes | no | no | no |
| Append-only prompt log | yes | no | no | no |
| MCP server | yes | no | no | no |
| Structured-error envelope with stable codes | yes | no | not documented | partial |
| Pluggable backend (Flux / DALL-E / Imagen on the same interface in v0.2+) | interface; backends v0.2+ | MJ only | MJ only | provider-locked |
| License | Apache-2.0 | Apache-2.0 | Apache 2.0 | proprietary |

---

## Three console scripts

- **`cascade-mj-bridge`** — the MJ-via-Discord daemon. Run once per session.
  - `--check-env` — JSON config validation with structured remediation.
  - `--doctor` — full pre-flight (env + Discord reachability + MCP server + discord.py-self imports).
- **`cascade-mcp`** — MCP server. Stdio by default (Claude Desktop / Cursor / Cline); `--http <port>` for hosts that prefer HTTP.
- **`cascade-mj`** — the CLI. Takes an `asset_id` and a registry, composes the prompt, fires, waits for the result, and writes a record to the prompt log.

All three emit structured JSON; all three follow the same `{ok, result | error: {code, remediation}}` envelope.

---

## Structured logging and errors

The daemon emits structured JSON log lines across the whole job lifecycle, and every failure carries a stable error `code` (e.g. `DISCORD_401`, `MJ_UUID_MISSING`, `UPSCALE_BUTTON_FAILED`) — so a caller branches on the code instead of parsing a message. The full catalog of log events and error codes is in [vocabulary/0.1.json](./vocabulary/0.1.json), and each failure mode's remediation is in [RUNBOOK.md](./RUNBOOK.md).

---

## Documentation

- **[RUNBOOK.md](./RUNBOOK.md)** — install, env capture, the setup procedure, the reconnect lifecycle, and every known failure mode with its structured error code and remediation.
- **[AGENTS.md](./AGENTS.md)** — the LLM operator's guide. Read this when handing cascade-img to an agent.
- **[CAPABILITIES.md](./CAPABILITIES.md)** — exactly which Midjourney v7 features cascade-img drives (every prompt parameter and `mj_action`, what each does) and what's intentionally not wired.
- **[TOS.md](./TOS.md)** — the technical context: Midjourney has no public API; Discord user-account automation is the established OSS pattern; both Discord's and Midjourney's Terms of Service prohibit it.
- **[examples/](./examples/)** — two short, generic walkthroughs of the operating loop (generate one image; generate a batch). Illustrative, not templates to copy verbatim. Read AGENTS.md before any of these.

## Repository layout

```
cascade-img/
├── packages/python/        # the Python package (import name: cascade_img) — the product
│   ├── src/cascade_img/     #   prompt/, interfaces/, backends/, curation/, vocabulary/
│   ├── tests/               #   behavior tests
│   └── tools/               #   live smoke walk
├── packages/typescript/        # npm name reservation for the v0.2 TypeScript wrapper (placeholder)
├── examples/              # two short, generic walkthroughs of the operating loop
├── vocabulary/0.1.json     # mirror of the package's event log-line catalog
└── *.md                    # README, ARCHITECTURE, RUNBOOK, AGENTS, AGENT_RUNDOWN, SECURITY, SUPPORT, …
```

The product is `packages/python`. Everything an operator or agent needs is the
top-level Markdown plus that package.

## Roadmap

| version | headline |
|---|---|
| v0.1 (current) | MJ V7 backend, prompt composer, curation kit (crop + flood-fill alpha key + promote), MCP server, AGENTS.md, prompt templates, Python package. **Python-only** — TypeScript wrapper is a v0.2 deliverable (the `@greenrosesystems/cascade-img` placeholder on npm reserves the name). |
| v0.2 | TypeScript wrapper (BridgeClient + PromptComposer + Zod types + Node-native MCP server), Flux via Fal + OpenAI `gpt-image-1` backends, Windows bridge |
| v0.3 | Flux Kontext (instruction-edit), bundled-binary install path |
| v0.4 | Imagen, Ideogram, Recraft backends |
| v1.0 | API stable across two minor releases, three backends in production |

Because every backend implements one interface, a later release can chain them: generate on one provider, refine or instruction-edit on a second (e.g. Flux Kontext), then upscale or restyle on a third — passing each image as the next step's input. cascade-img becomes the relay that moves an image between providers, using each for what it does best.

The HTTP contract between the bridge and the client is the main boundary between the two packages; changes there are coordinated across both.

## License

Apache-2.0. See [LICENSE](./LICENSE).

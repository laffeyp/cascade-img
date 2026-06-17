# cascade-img

[![PyPI](https://img.shields.io/pypi/v/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![Python](https://img.shields.io/pypi/pyversions/cascade-img.svg)](https://pypi.org/project/cascade-img/)
[![CI](https://github.com/laffeyp/cascade-img/actions/workflows/ci.yml/badge.svg)](https://github.com/laffeyp/cascade-img/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)

An image-generation pipeline an LLM can drive. It runs Midjourney through Discord today; it will run other image generation service API's using the same interface later.

Midjourney is a text-to-image generator: you write a sentence describing a picture — "a flat-design icon of a mountain" — and it paints it, one of the strongest models for stylized, art-directed work. You drive it with an `/imagine <prompt>` command and it answers with a 2×2 grid of four candidates; you pick one and *upscale* it to full resolution. (It needs a paid subscription — [midjourney.com](https://midjourney.com).)

cascade-img wraps that flow. The Midjourney prompt is split into composable parts you set independently, a JSONL log records every attempt so the next iteration knows what's been tried, and an MCP server — the protocol [Claude Desktop, Cursor, and Cline](https://modelcontextprotocol.io) use to call tools — exposes the whole thing so an agent can compose, generate, curate, and log without a human on every attempt.

## How you actually use it

The intention is that your own words are the interface. Instead of learning Midjourney's prompt syntax or clicking through Discord, you tell an AI assistant what you want and it drives everything:

- **Ask in plain language** — "a set of flat-design weather icons, all in one style" — and the assistant builds the actual Midjourney prompt from reusable parts (subject, style reference, aspect ratio) for you.
- **It runs the loop** — generates the four candidates, waits, looks at them, picks the best, crops and cleans it up, and saves it to a known folder. No command line, no `/imagine`.
- **Everything is recorded** — each attempt (the prompt, the result, why it was kept or re-rolled) goes into a log the assistant reads back the next round, so it builds on what's been tried instead of starting over.
- **You iterate by talking** — "tighter and more minimal," "three more like the second one," "now a wide version for a banner." It re-rolls, varies, zooms, pans, or animates without you learning any of those commands.

In practice you can go from an idea to a folder of finished, consistent, organized assets in a single conversation — generating and discarding options far faster than by hand, with a written trail of exactly what produced each final image. The CLI and Python API are there for scripting and embedding, but the agent loop is the point; [AGENTS.md](./AGENTS.md) is the guide an assistant reads once.

## No idea what you're doing? Start here

You don't have to be a programmer, or know what any of the above means. The tool is built to be run by an AI assistant, and it ships with a step-by-step setup guide ([RUNBOOK.md](./RUNBOOK.md)) written for exactly that. Open an AI assistant that can run commands on your computer — [Claude Code](https://claude.com/claude-code), Cursor, or Cline — point it at this repository, and ask it to do the whole thing for you:

> Read RUNBOOK.md and set up cascade-img on this machine, then let me make images by describing them to you. Walk me through the couple of steps only I can do.

It has the full context — the guide lists every step and everything that can go wrong — so it runs the commands, handles the technical parts, and answers your questions as they come up. The two steps that are yours, a Midjourney subscription and copying a couple of values out of Discord, it walks you through as well.


Midjourney comes first by design. Midjourney has no public API, so driving it through a Discord account is actually already an established way of using it. It is tackled first precisely because it is more work. With that done, adding the other integrations is the easier work.

> **Context.** Midjourney has no public API. Driving it through a Discord user account is the established OSS pattern for programmatic access. Of course, both Discord and Midjourney's Terms of Service prohibit user-account automation. See [TOS.md](./TOS.md).

---

## Why this exists

This exists so that a person driving an LLM can now easily and programmatically generate visual assets via Midjourney. This is extremely useful in a number of settings, and allows someone with a good idea of what they want visually to get there much quicker.  It allows someone who doesn't to experiment faster. 

Most of the loop is mechanical: compose the prompt from reusable parts, fire it, wait, crop and curate the result, write down what was tried.  No existing open-source Midjourney driver let an agent run the loop end to end, so cascade-img provides it.

---

## Quickstart

**Before you start, you need:**

- A **paid Midjourney subscription** ([midjourney.com](https://midjourney.com)).
- A **Discord account where you can run `/imagine`** and get a grid back — i.e. the Midjourney bot is in one of your channels. New to this: subscribe to Midjourney and use it [through Discord](https://docs.midjourney.com/hc/en-us/sections/32013439485197-Using-Discord), or invite the MJ bot to your own server.
- **Python 3.14** (`brew install python@3.14` on macOS) — cascade-img targets the latest stable Python.
- About five minutes to capture three values from the Discord desktop app's DevTools (token, channel ID, command version); [RUNBOOK.md](./RUNBOOK.md) walks each one.

cascade-img drives *your own* Midjourney account and runs locally on your machine.

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

Leave it running. Both entry points below connect to it over local HTTP.

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

## Midjourney terms

The Midjourney shorthand the rest of these docs use:

**prompt** — the text + flags you send Midjourney · **grid** — the 2×2 set of four candidates Midjourney returns per prompt · **quadrant / U1–U4** — the four cells of the grid; "U2" means upscale the second · **upscale** — render one cell at full resolution · **aspect ratio (`--ar`)** — output shape (1:1, 16:9, …) · **sref** — an image whose *style* Midjourney should borrow · **oref** — an image whose *subject identity* it should keep across new poses/angles · **moodboard (`--p`)** — a saved Midjourney personalization profile · **stylize (`--s`)** — how strongly Midjourney applies its own aesthetic (lower = more literal).

---

## How this differs

Most Midjourney drivers focus on the generation step itself — fire the prompt, hand back the image. cascade-img does the work around that: it builds the prompt from reusable named parts, crops and cleans up the result, and keeps a record of every attempt so each round can build on the last.

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
    version="7",  # oref (omni-reference identity lock) is V7-only; omit it to use the V8.1 default
)
```

Other open-source options exist — [erictik/midjourney-api](https://github.com/erictik/midjourney-api) (a Node library), [novicezk/midjourney-proxy](https://github.com/novicezk/midjourney-proxy) (a Java HTTP proxy), and a few paid REST proxies that wrap the same Discord mechanism behind a hosted API. Any of them will get you a generated image.

What cascade-img adds is the work *around* the generation: composable prompt parts instead of raw strings, curation tools (grid crop, alpha key, promote), an append-only prompt log, an MCP server so an LLM agent can run the whole loop, and a structured-error envelope with stable codes — with one backend interface so Flux, DALL-E, and Imagen can slot in later (v0.3+). If you just need to fire a prompt and get an image back, the simpler drivers are a fine fit; cascade-img is for driving the full iterate-and-curate loop, especially from an agent.

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

The daemon emits structured JSON log lines across the whole job lifecycle, and every failure carries a stable error `code` (e.g. `DISCORD_401`, `MJ_UUID_MISSING`, `UPSCALE_BUTTON_FAILED`) — so a caller branches on the code instead of parsing a message. The full catalog of log events and error codes is in [vocabulary/0.1.json](./vocabulary/0.1.json), and each failure mode's remediation is in [RUNBOOK.md](./RUNBOOK.md). The catalog also declares the legal order of those events (which must precede which, per `job_id`) and their timing bands; a trace checker (`cascade-trace-check`) enforces those rules over a recorded run, and the test suite runs it on every CI change and against each live end-to-end run.

---

## Documentation

- **[RUNBOOK.md](./RUNBOOK.md)** — install, env capture, the setup procedure, the reconnect lifecycle, and every known failure mode with its structured error code and remediation.
- **[AGENTS.md](./AGENTS.md)** — the LLM operator's guide. Read this when handing cascade-img to an agent.
- **[CAPABILITIES.md](./CAPABILITIES.md)** — exactly which Midjourney features cascade-img drives (every prompt parameter and `mj_action`, the V8.1/V7 version split, what each does) and what's intentionally not wired.
- **[TOS.md](./TOS.md)** — the technical context: Midjourney has no public API; Discord user-account automation is the established OSS pattern; both Discord's and Midjourney's Terms of Service prohibit it.
- **[examples/](./examples/)** — two short, generic walkthroughs of the operating loop (generate one image; generate a batch). Illustrative, not templates to copy verbatim. Read AGENTS.md before any of these.

## Repository layout

```
cascade-img/
├── packages/python/        # the Python package (import name: cascade_img) — the product
│   ├── src/cascade_img/     #   prompt/, interfaces/, backends/, curation/, vocabulary/
│   ├── tests/               #   behavior tests
│   └── tools/               #   live smoke walk
├── packages/typescript/        # npm name reservation for the v0.3 TypeScript wrapper (placeholder)
├── examples/              # two short, generic walkthroughs of the operating loop
├── vocabulary/0.1.json     # mirror of the package's event log-line catalog
└── *.md                    # README, ARCHITECTURE, RUNBOOK, AGENTS, AGENT_RUNDOWN, SECURITY, SUPPORT, …
```

The product is `packages/python`. Everything an operator or agent needs is the
top-level Markdown plus that package.

## Roadmap

| version | headline |
|---|---|
| v0.1 (current) | MJ backend (version-aware: V8.1 default, V7 for the `--oref` identity lock), prompt composer, curation tools (crop + flood-fill alpha key + promote), MCP server, AGENTS.md, prompt templates, Python package. |
| v0.2 | More Midjourney commands (`/describe`, `/show`, Vary Region inpaint, `/blend`, `/shorten`, `/tune`, `/info`); internal code cleanup — break apart the large bridge module and split the long ingest function. |
| v0.3 | A TypeScript wrapper; the first API backends — [Flux](https://bfl.ai/) via [Fal](https://fal.ai/) (with instruction-edit through [Flux Kontext](https://bfl.ai/models/flux-kontext)) and [Ideogram](https://ideogram.ai/) for reliable in-image text; Windows bridge. |
| v0.4 | More backends — [Google Imagen](https://deepmind.google/models/imagen/) and [Recraft](https://www.recraft.ai/) (native vector/SVG output); bundled-binary install path. |
| v0.5 | [OpenAI gpt-image](https://openai.com/api/) and [Stable Diffusion](https://stability.ai/stable-image) backends. |
| v1.0 | API stable across two minor releases, three backends in production |

Because every backend implements one interface, a later release can chain them: generate on one provider, refine or instruction-edit on a second (e.g. Flux Kontext), then upscale or restyle on a third — passing each image as the next step's input. cascade-img becomes the relay that moves an image between providers, using each for what it does best.

The HTTP contract between the bridge and the client is the main boundary between the two packages; changes there are coordinated across both.

## License

Apache-2.0. See [LICENSE](./LICENSE).

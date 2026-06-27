# cascade-img

[![CI](https://github.com/laffeyp/cascade-img/actions/workflows/ci.yml/badge.svg)](https://github.com/laffeyp/cascade-img/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](./LICENSE)
[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![MCP Tools: 20](https://img.shields.io/badge/MCP_Tools-20-green.svg)](./AGENTS.md)

<!-- TODO: hero image — pipeline collage: prompt → grid → crop → finished asset -->

Generate Midjourney images by conversation instead of by hand. You describe what you want; your AI assistant composes the prompt, fires it, inspects the grid with vision, crops the best quadrant, cleans it up, and logs what worked.

```
You: "I need a flat-design mountain icon, centered, simple shapes, transparent background"

Agent: reads prompt log → composes prompt from parts → fires imagine →
       waits → inspects 2x2 grid with vision → picks best quadrant →
       crops it → removes background → saves → logs what worked
```

cascade-img is an MCP server with 20 tools that plugs into Claude, Cursor, Codex, or anything that speaks [MCP](https://modelcontextprotocol.io). Midjourney is the first backend; Flux, DALL-E, and Imagen are on the [roadmap](#roadmap). There's also a CLI.

> **Not a programmer?** Open an AI assistant that can run commands ([Claude Code](https://claude.com/claude-code), Cursor, or Cline), point it at this repo, and say: *"Read RUNBOOK.md and set up cascade-img on this machine, then let me make images by describing them to you."* It does the technical parts. You just need a Midjourney subscription and to copy a few values from Discord.

---

## Quick Start

**You need:** a [paid Midjourney subscription](https://midjourney.com), a Discord account with the MJ bot in a channel, and Python 3.14.

```bash
git clone https://github.com/laffeyp/cascade-img
cd cascade-img/packages/python
pip install -e .
```

This puts three commands for operating cascade-img on your PATH: `cascade-mj-bridge` (the daemon), `cascade-mcp` (the MCP server), and `cascade-mj` (the CLI). Installing also adds a fourth command, `cascade-trace-check` — a diagnostics validator (not part of the generation loop) that replays a recorded event log and checks it against the vocabulary's declared event ordering and timing rules.

**Configure** — you need four values from the Discord desktop app (channel ID, server ID, imagine version, and your user token). Takes about five minutes. [RUNBOOK.md](./RUNBOOK.md) walks through each one step by step.

```bash
cp "$(python -c 'import cascade_img, pathlib; print(pathlib.Path(cascade_img.__path__[0]) / ".env.example")')" .env
# Fill in the four values per RUNBOOK.md, then validate:
cascade-mj-bridge --check-env --pretty
```

**Start the daemon** in one terminal, then connect from another:

```bash
cascade-mj-bridge          # leave running — holds the Discord connection
```

**Connect your AI assistant** — add to your MCP config (Claude Desktop, Cursor, Cline):

```json
{
  "mcpServers": {
    "cascade-img": {
      "command": "cascade-mcp"
    }
  }
}
```

Or point your assistant at this repo and ask it to read [AGENTS.md](./AGENTS.md) — it'll wire everything up.

**Or use the CLI:**

```bash
echo '{
  "mountain-icon": {
    "subject": "a flat-design icon of a mountain, centered, simple shapes",
    "aspect_ratio": "1:1"
  }
}' > assets.json

cascade-mj mountain-icon --registry assets.json --upscale all --pretty
```

---

## The 20 Tools

| Category | Tools | What they do |
|----------|-------|-------------|
| **Generation** | `imagine`, `generate_video`, `wait`, `status`, `bridge_health`, `mj_action` | Compose and fire prompts, poll for results, check daemon health, trigger Midjourney actions (upscale, vary, pan) |
| **Composition** | `compose_prompt`, `compose_video` | Build prompts from structured parts — subject, moodboard, style refs, aspect ratio, negatives — not freeform text |
| **Curation** | `crop_grid`, `alpha_key`, `auto_trim`, `palette_quantize`, `contact_sheet`, `sprite_sheet`, `score_grid`, `video_filmstrip`, `loop_seam_delta`, `promote` | Extract quadrants from grids, remove backgrounds, trim whitespace, build sprite sheets, score results with vision, promote winners to final output |
| **Working memory** | `log_append`, `read_prompt_log` | Append-only prompt log the agent reads before every run — what was tried, what worked, what didn't. Persists across sessions. |

Every call returns `{ok, result}` or `{ok: false, error: {code, remediation}}`. Branch on the stable `code`, not the message. Full tool reference in [AGENTS.md](./AGENTS.md).

---

## How This Differs

Other open-source Midjourney tools focus on the generation step — fire the prompt, hand back the image. cascade-img does the work around that:

- **Vision-based self-curation** — the agent inspects its own output and picks the best quadrant
- **Structured prompt composition** — prompts built from parts (subject, style, identity, constraints), not raw strings
- **Working memory** — append-only log persists across sessions; each run reads what came before
- **Curation pipeline** — crop grids, remove backgrounds, build sprite sheets, promote winners
- **MCP-native** — 20 tools that plug into Claude, Cursor, Codex, or anything that speaks MCP
- **Pluggable backends** — Midjourney now, Flux/DALL-E/Imagen on the roadmap

---

## How It Works

One daemon, two stateless clients, all over local HTTP:

- **`cascade-mj-bridge`** — the daemon. Only process that talks to Discord. Holds the live connection and tracks in-flight jobs. Must stay running.
- **`cascade-mcp`** — the MCP server. Stdio by default (Claude Desktop / Cursor / Cline); `--http <port>` for HTTP. Stateless — start and stop freely.
- **`cascade-mj`** — the CLI. Takes an asset ID and a registry, composes the prompt, fires, waits, writes to the log.

Prompts are composed from structured parts, not written as raw strings:

```python
from cascade_img.prompt.composer import PromptComposer, Subject, StyleStack, IdentityStack

prompt = PromptComposer().compose(
    Subject(
        text="a flat-design icon of a mountain",
        constraints=["centered", "simple shapes", "transparent background"],
    ),
    # Both optional. moodboard is a Midjourney personalization code;
    # sref/oref are reference-image URLs you'd set up in MJ first.
    style=StyleStack(moodboard="abc123def", sref="https://cdn.example.com/style.png"),
    identity=IdentityStack(oref="https://cdn.example.com/ref.png", ow=1000),
    aspect_ratio="1:1",
    version="7",
)
```

All three entry points emit structured JSON and follow the same `{ok, result | error: {code, remediation}}` envelope. Every failure carries a stable error code (e.g. `DISCORD_401`, `MJ_UUID_MISSING`, `UPSCALE_BUTTON_FAILED`) with a machine-readable remediation — so a caller branches on the code, not the message. The full catalog of log events and error codes is in [vocabulary/0.1.json](./vocabulary/0.1.json), and a trace checker (`cascade-trace-check`) enforces event ordering over recorded runs.

<details>
<summary><strong>Midjourney terminology</strong></summary>

**prompt** — the text + flags you send Midjourney. **grid** — the 2x2 set of four candidates returned per prompt. **quadrant / U1-U4** — the four cells; "U2" means upscale the second. **upscale** — render one cell at full resolution. **aspect ratio (`--ar`)** — output shape. **sref** — an image whose *style* to borrow. **oref** — an image whose *subject identity* to keep across poses. **moodboard (`--p`)** — a saved personalization profile. **stylize (`--s`)** — how strongly MJ applies its own aesthetic.

</details>

---

## Documentation

| Doc | What it covers |
|-----|---------------|
| [AGENTS.md](./AGENTS.md) | The LLM operator's guide. Read this when handing cascade-img to an agent. |
| [RUNBOOK.md](./RUNBOOK.md) | Install, env capture, setup, reconnect lifecycle, every failure mode with error codes and fixes. |
| [CAPABILITIES.md](./CAPABILITIES.md) | Every Midjourney feature cascade-img drives — prompt parameters, mj_actions, the V8.1/V7 split. |
| [ARCHITECTURE.md](./ARCHITECTURE.md) | Internal architecture and design decisions. |
| [examples/](./examples/) | Three walkthroughs: single image, batch, video. Read AGENTS.md first. |
| [CHANGELOG.md](./CHANGELOG.md) | Release history. |

---

## Roadmap

| Version | What's in it |
|---|---|
| **v0.1** (current) | MJ backend (V8.1 + V7), prompt composer, curation tools, MCP server, CLI, prompt log |
| **v0.2** | More MJ commands (`/describe`, `/blend`, Vary Region inpaint, `/tune`); internal refactoring |
| **v0.3** | TypeScript wrapper; first API backends — [Flux](https://bfl.ai/) via [Fal](https://fal.ai/) + [Flux Kontext](https://bfl.ai/models/flux-kontext), [Ideogram](https://ideogram.ai/) |
| **v0.4** | [Google Imagen](https://deepmind.google/models/imagen/), [Recraft](https://www.recraft.ai/) (native vector/SVG) |
| **v0.5** | [OpenAI gpt-image](https://openai.com/api/), [Stable Diffusion](https://stability.ai/stable-image) |
| **v1.0** | API stable, three+ backends in production |

Every backend implements one interface, so a later release can chain them — generate on one provider, refine on a second (e.g. Flux Kontext), upscale on a third.

---

## Repository Layout

```
cascade-img/
├── packages/python/        # the Python package (cascade_img)
│   ├── src/cascade_img/    #   prompt/, interfaces/, backends/, curation/, vocabulary/
│   ├── tests/              #   behavior tests
│   └── tools/              #   live smoke walk
├── examples/               # three walkthroughs of the operating loop
├── vocabulary/0.1.json     # event log-line catalog
└── *.md                    # README, ARCHITECTURE, RUNBOOK, AGENTS, CAPABILITIES, ...
```

---

## Disclaimer

This tool automates Midjourney through a Discord user account. A paid Midjourney subscription is required. Both Discord and Midjourney's Terms of Service prohibit user-account automation. This is the same mechanism used by every open-source MJ tool ([midjourney-proxy](https://github.com/novicezk/midjourney-proxy), [midjourney-api](https://github.com/erictik/midjourney-api), etc.) — there is no public Midjourney API. Use at your own risk.

The backend interface is pluggable — Flux, DALL-E, and Imagen are on the [roadmap](#roadmap).

## License

Apache-2.0. See [LICENSE](./LICENSE).

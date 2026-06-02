# Cascade-MJ — Product Specification

*The canonical "what this is, who it's for, what it does, why it exists" document. Written 2026-05-26. Companion to `CASCADE-MJ-PACKAGING-AND-PUBLIC-RELEASE-PLAN.md` (how it ships) and the operational runbook at `handoff/cascade-asset-pipeline-runbook.md` (how it runs). When this spec and either of those disagree, this spec wins; they're the implementation views.*

---

## 1. Tagline

**An LLM-operable image-generation pipeline for Midjourney (today) and any sanctioned image API (tomorrow), with composable V7-style facets, curation utilities, and reproducible prompt history.**

---

## 2. The problem

Three problems converge:

**An LLM driving a real creative project needs to generate images on demand, see the result, decide whether to refine, and iterate — all without a human in the loop for every roll.** No tool today gives an LLM this loop cleanly. Existing Midjourney drivers expose `imagine` as a command; nothing exposes the curate-decide-refine-promote-log cycle as a first-class agent surface.

**Midjourney has no usable API for individual developers.** The Enterprise API announced in July 2025 is application-only and inaccessible to anyone who isn't a Fortune-500 marketing org. The paid third-party REST proxies (TheNextLeg, PIAPI, useapi.net, GoAPI) are convenient but still run Discord self-bots under the hood, charge $20–$50/month, vendor-lock prompts through their infrastructure, and shift ToS exposure onto pools of accounts they own. The only OSS path is to run your own Discord self-bot bridge, which several abandoned 2023-era projects attempted and one actively-maintained TypeScript project (`erictik/midjourney-api`) does well — but none of them ship the V7 facet composition, the curation utilities, the prompt log, or anything resembling an agent-readable surface.

**The state of the art has moved past MJ on programmatic axes.** Flux Pro 1.1 and Flux Kontext (Black Forest Labs, via Fal/Replicate) match or exceed MJ V7 on photoreal and on instruction-following, and ship with sanctioned APIs. OpenAI's `gpt-image-1` composes natively with the rest of GPT for vision-in-the-loop editing. Imagen 3 and Ideogram dominate text rendering. MJ retains an aesthetic edge — the painterly, considered default that still wins on sprite art, illustration, and stylized work — but for many use cases there's already a sanctioned alternative that's technically superior. A tool that locks users to MJ specifically is solving a problem that's shrinking, not growing.

**Cascade addresses all three by treating image generation as an orchestration layer, MJ as the first backend, and the LLM as the primary user.**

---

## 3. The product

Cascade is a Python package (with a TypeScript wrapper) that provides:

- A **local HTTP bridge** that drives Midjourney through a Discord user account (the only OSS path), with two production-tested patches that fix gaps in the upstream self-bot pattern.
- A **facet-composition layer** that treats V7's `--p` (moodboard), `--sref` (style reference), `--oref` (omni-reference identity lock), and `--ow` (omni-weight) as independently stackable composable parameters, not opaque strings.
- A **curation toolkit** for the operations the LLM has to do after every roll: grid-quadrant cropping, four-corner-average alpha-keying to fix MJ's "transparent background" failures, and winner promotion into a project's asset tree.
- An **append-only prompt log** that doubles as the LLM's working memory: every roll's prompt, parameters, outputs, errors, and the agent's decision, structured and readable back.
- An **MCP server** that exposes the entire loop as tools an agent host can invoke directly.
- A **pluggable backend interface** so the same orchestration layer works against Flux, DALL-E, Stable Diffusion, or any future sanctioned API with a backend implementation that's a few hundred lines of HTTP wrapping.
- A **CLI with `--json` mode** for non-MCP agent hosts and human script users.
- An **agent-readiness asset bundle** (`AGENTS.md`, prompt templates, structured-error remediation contract) so an LLM dropped into the project knows how to use the tool the moment it's installed.

Two installs (`pip install cascade-mj`, `npm install @cascade/mj-client`), one MCP config block, three audiences served well, one canonical implementation.

---

## 4. Users

In priority order. Design decisions get made for the higher-priority user when they conflict.

**Primary: an LLM agent operating inside Claude Desktop, Cursor, Cline, Continue, or a custom agent framework.** Discovers Cascade through an MCP server registry or a config block dropped in by the human. Reads `AGENTS.md` to understand the project. Operates the full generate-curate-refine-promote-log loop autonomously, only consulting the human for the initial creative guidance (moodboard, character reference, aesthetic intent) and for the rare structural decision an LLM shouldn't make alone.

**Secondary: an indie game developer or sprite artist generating asset libraries for a project.** Installs via pip or npm. Wires the CLI into their build pipeline or runs it ad-hoc. Treats Cascade as a scriptable replacement for "manually pasting prompts into Discord, screenshotting upscales, alpha-keying in Photoshop." The Katybird repo is the canonical example consumer.

**Tertiary: a web or app developer generating images on demand.** Installs via npm. Calls Cascade from a Node service. Cares less about the curation flow, more about the bridge reliability and the prompt-composition ergonomics. May not use Midjourney at all — may install Cascade specifically for the pluggable-backend orchestration over Flux or DALL-E once those backends ship.

**Quaternary: a Python ML or AI tooling developer building an agent framework.** Imports `cascade_mj` directly and embeds the `BridgeClient` and `PromptComposer` into a larger pipeline. May fork the MCP server, may ignore it.

---

## 5. Core experience — the LLM loop

This is the loop Cascade exists to close. Every design decision below serves it.

```
HUMAN provides creative guidance, ONCE:
    moodboard ID
    character style reference URL
    optional identity-lock reference image

LLM AGENT receives a list of assets to generate:
    [{asset_id, subject_description}, ...]

LLM AGENT runs the loop, PER ASSET:

    1. compose prompt
        subject (from human's asset description)
        + style stack (moodboard + sref + optional --s)
        + identity stack (oref + ow, if locking to a reference)
        + aspect ratio
        → v7 prompt string

    2. fire generation
        BridgeClient.imagine(prompt, asset_id, upscale="grid")
        BridgeClient.wait(job_id, timeout=180)
        → grid PNG at deterministic path

    3. read the result
        agent reads the PNG with vision
        → "is this on-aesthetic? does it match the identity?
          which of the four grid quadrants is best?"

    4. decide
        promote → curate_kit.crop_grid(asset_id, quadrant=N)
                + curate_kit.alpha_key(asset_id)
                + curate_kit.promote(asset_id, dest_path)
        re-roll → BridgeClient.imagine(...) again
        escalate identity lock → bump ow from 100 to 400 to 1000
        tighten subject language → add explicit constraints
        give up and ask human → only when stuck after N attempts

    5. log the decision
        prompt_log.append(asset_id, prompt, job_id, outputs,
                          decision, reason)
        → working memory for the next pass

LOOP exits when all assets are promoted to the project tree.
```

The loop is closeable end-to-end without human intervention for the common case. The human's only obligations after initial guidance are (a) accepting the final asset set and (b) answering questions the agent escalates when it's genuinely blocked (account banned, MJ rejected prompt, identity lock won't bite even at `ow=1000`).

---

## 6. Architecture

Six components. The first four are the engine, the last two are the surfaces.

### 6.1 BackendInterface

The pluggable seam. An abstract Python class with a small surface:

```
class ImageGenerationBackend:
    async def imagine(prompt: str, asset_id: str, upscale) -> Job
    async def wait(job_id: str, timeout: int) -> JobResult
    async def status(job_id: str) -> JobStatus
    async def health() -> HealthReport
    capabilities: BackendCapabilities  # which facets it supports
```

Backends shipped in v0.1: `MidjourneyDiscordBackend` (the current bridge). Backends planned: `FluxFalBackend`, `FluxReplicateBackend`, `DallE3OpenAIBackend`, `StableDiffusionStabilityBackend`, eventually `MidjourneyOfficialBackend` if/when the Enterprise API generalizes. Adding a backend is a few hundred lines of HTTP wrapping plus a capability declaration; everything above this line in the architecture is backend-agnostic.

### 6.2 PromptComposer

Takes structured inputs:

```
Subject(text: str, constraints: list[str])
StyleStack(moodboard: str | None, sref: str | None, s: int | None)
IdentityStack(oref: str | None, ow: int | None)
AspectRatio("1:1" | "16:9" | "9:16" | ...)
```

Emits the backend-specific prompt string. For MJ V7, that's the `--p`, `--sref`, `--oref`, `--ow`, `--ar`, `--v 7`, `--style raw` form Cascade already produces. For Flux, that's a JSON payload with `prompt`, `reference_image`, `strength` fields. The composer knows the dialect for each backend; the consumer never writes raw prompt strings.

This is the single most-differentiated piece of Cascade. No other OSS tool exposes V7 facets as independently composable inputs.

### 6.3 BridgeClient (and direct-backend client)

For MJ via Discord, this is the HTTP client against the local bridge daemon. For sanctioned-API backends, the "bridge" is just the provider's REST API — no daemon needed. The client interface is the same; the backend implementation differs.

### 6.4 CurationKit

`crop_grid(asset_id, quadrant)`: extract one of the four 2×2 grid panels into a single image. `alpha_key(asset_id, corner_sample=True)`: average the four corner pixel colors and key out a tolerance band — the practical fix for MJ ignoring "transparent background" about half the time. `promote(asset_id, dest_path)`: move a curated winner from the staging directory into the project's asset tree. All three available as Python functions, CLI subcommands, and MCP tools.

### 6.5 PromptLog

Append-only markdown ledger. Every roll's `timestamp`, `asset_id`, `backend`, `prompt`, `params`, `job_id`, `outputs`, `error`, `agent_decision`, `agent_reason`. Readable by humans, parseable by LLMs (the `read_prompt_log` MCP tool returns structured objects, not markdown text). The log is the LLM's working memory across loop iterations — the answer to "what have I tried for this asset already?"

### 6.6 Surfaces

Three surfaces, one engine:

1. **CLI** — `cascade-mj <asset_id> [--upscale grid|1|2|3|4|all] --registry path/to/assets.{ts,js,json} [--json]`. Every command supports `--json`; stdout becomes a single structured object. The contract for non-MCP agent hosts and for human script users.
2. **MCP server** — `cascade-mj-mcp`. Exposes `imagine`, `wait`, `status`, `crop_grid`, `alpha_key`, `promote`, `read_prompt_log`, `compose_prompt`, `list_backends`, `set_backend` as tools with JSON schemas. Stdio transport by default; HTTP optional. The primary surface for LLM agents.
3. **Python library** — `from cascade_mj import BridgeClient, PromptComposer, CurationKit, PromptLog`. The contract for Python consumers who want the engine directly.

The TypeScript package (`@cascade/mj-client`) wraps the CLI as a typed Node API and ships its own MCP server entry point for Node-native agent hosts. Underneath it spawns the Python engine; no logic is duplicated.

---

## 7. Backend support

| Backend | v0.1 | Planned | Status |
|---|---|---|---|
| Midjourney via Discord self-bot | yes (default) | — | Production-tested in Katybird |
| Flux Pro / Dev / Schnell via Fal | — | v0.2 | Sanctioned API, no self-bot |
| Flux via Replicate | — | v0.2 | Sanctioned API |
| Flux Kontext (instruction-edit) | — | v0.3 | The closest sanctioned analog to MJ Vary Region |
| OpenAI DALL-E 3 / `gpt-image-1` | — | v0.2 | Sanctioned; composes with GPT |
| Stable Diffusion 3.5 via Stability API | — | v0.3 | Sanctioned |
| Google Imagen 3 (Vertex AI) | — | v0.4 | Sanctioned; strongest text rendering |
| Ideogram | — | v0.4 | Sanctioned; text-in-image specialist |
| Recraft V3 | — | v0.4 | Sanctioned; vector output |
| Midjourney Official Enterprise API | — | when available | Will replace the self-bot backend if it generalizes |

The roadmap is realistic, not aspirational. Flux via Fal is the highest-leverage second backend: largest model family, fastest hosting, the best sanctioned MJ competitor. Shipping Flux at v0.2 gives every Cascade user a ToS-clean fallback within the first two months of public release.

Backend capabilities are declared explicitly. `MidjourneyDiscordBackend.capabilities.facets = ["moodboard", "sref", "oref", "ow", "style_raw"]`. `FluxFalBackend.capabilities.facets = ["reference_image", "strength", "guidance_scale"]`. The composer adapts; the agent can query capabilities and degrade gracefully.

---

## 8. Distribution

See `CASCADE-MJ-PACKAGING-AND-PUBLIC-RELEASE-PLAN.md` for full mechanics. Summary:

- **PyPI:** `cascade-mj` — bridge + curation + MCP server + Python library + CLI.
- **npm:** `@cascade/mj-client` — TS wrapper, auto-installs the Python engine via `uv tool install` postinstall hook (Tier 2) at v0.1, upgrades to bundled PyInstaller binary (Tier 3) at v0.3.
- **GitHub:** `cascade-mj` monorepo, MIT licensed.
- **MCP server registries:** primary discovery channel. `modelcontextprotocol/servers`, `awesome-mcp-servers`, `mcp.so`, Smithery.
- **Launch story:** a technical blog post framed around the LLM-feedback-loop angle, with the Sprint 4.0 and 4.7 patches as the narrative (every one of which was found by an LLM running the loop, not a human running commands). Show HN same day. Cross-post to relevant communities (`r/ClaudeAI`, `r/Cursor`, `r/midjourney`, `r/gamedev`, `r/Phaser`).

---

## 9. Agent-readiness assets

This is the moat. None of the surveyed competitors ship any of this. All of it is required at v0.1.

- **`AGENTS.md`** at repo root, following the emerging convention. Describes Cascade's purpose, the tool surface, the loop pattern, the failure modes with remediation, the facet semantics, the curation flow. An LLM reads this once and knows how to operate Cascade.
- **`prompts/`** directory with bundled system-prompt templates: `prompts/generate-sprite-set.md`, `prompts/generate-character-locked-variants.md`, `prompts/generate-region-backdrop.md`, `prompts/refine-existing-asset.md`. Drop into any agent host as a system prompt.
- **Structured-error remediation contract.** Every error returned from the CLI's `--json` mode and every MCP tool response carries `code`, `message`, `remediation`. The four real MJ failure modes (bridge down, Discord not ready, MJ command outdated, token expired) plus backend-specific failures (Flux rate limit, OpenAI safety reject) each have a stable error code an LLM can branch on.
- **Deterministic output paths.** `cascade-mj <asset_id>` writes to a path computable from `asset_id` alone. The MCP tool response includes the path string explicitly.
- **Prompt log as working memory.** `read_prompt_log` MCP tool returns the last N entries as structured objects. The LLM can answer "what have I already tried for this asset?" without scraping prose.
- **`--check-env`** subcommand on the bridge that validates configuration end-to-end and prints structured remediation for each missing or wrong value. The Sprint 4.0 `MJ_GUILD_ID` trap is the worked example: the original failure mode was Discord 400 "Unknown Channel" (unrecoverable for an LLM); the remediated mode is `{"code": "MISSING_GUILD_ID", "remediation": "Add MJ_GUILD_ID to .env; OPERATIONS §setup §4"}` (recoverable).

The README's first paragraph: *"You can run Cascade by hand. But the install is one config block in Claude Desktop, Cursor, or Cline, and the agent knows how to use it the moment it's installed."*

---

## 10. Differentiation

| | Cascade | erictik/midjourney-api | novicezk/midjourney-proxy | Paid REST proxies | Sanctioned alternatives |
|---|---|---|---|---|---|
| Drives MJ V7 | yes | partial | OSS no, paid fork yes | yes | n/a |
| V7 facet composition (`--oref`/`--ow` as first-class) | yes | no | no | passes raw strings | n/a |
| Local HTTP bridge | yes | no (library only) | yes (Java) | n/a (hosted) | n/a (hosted) |
| Curation utilities (grid split, alpha key, promote) | yes | no | no | no | no |
| Append-only prompt log | yes | no | no | no | no |
| MCP server | yes | no | no | no | no |
| `AGENTS.md` + prompt templates | yes | no | no | no | no |
| Structured-error remediation | yes | no | no | partial | varies |
| Pluggable backend (MJ + Flux + DALL-E + …) | yes | MJ only | MJ only | provider-locked | single backend |
| ToS posture | self-bot, explicit and honest | self-bot, mentioned | self-bot, mentioned | self-bot, hidden | sanctioned |
| License | MIT | MIT | Apache 2.0 | proprietary | proprietary |

Cascade competes on rows the others don't have. Where it overlaps (MJ self-bot driving, V7 partial), it's not the highest-leverage row. The rows that matter — agent-readiness, facet composition, curation, the pluggable backend — are unoccupied.

---

## 11. Non-goals

- **A web UI.** Cascade is a library, a CLI, and an MCP server. A separate project could build a UI on top.
- **A hosted SaaS.** Cascade runs locally. The user owns the Discord account, the API keys, the prompt log, the generated assets, and the ToS risk.
- **Audio or video generation.** Image only. The name reserves the option to ship `cascade-audio` and `cascade-video` later under the same monorepo, but they're separate products with separate backends.
- **A LoRA / fine-tuning pipeline.** Cascade is the orchestration layer over generation; finetuning is upstream of the generator.
- **A prompt engineer.** The PromptComposer composes structured inputs into the dialect of each backend. It does not invent prompts. The LLM agent does that, informed by the human's creative guidance.
- **Cross-platform parity for the bridge in v0.1.** The bridge runs on macOS and Linux. Windows support is a v0.2 item. The MCP server runs anywhere Python runs.

---

## 12. ToS posture

Cascade drives Midjourney through a Discord user account using `discord.py-self`. This is automation of a Discord account, which Discord's Terms of Service prohibit, and automation of Midjourney, which Midjourney's Terms of Service prohibit. Accounts get banned. Use a sacrificial Discord account.

This is the only OSS path to programmatic Midjourney access today. The paid REST proxies (TheNextLeg, PIAPI, useapi.net) shift the ToS exposure onto their account pools but do not eliminate it — they're running the same self-bot mechanism on accounts they own. Midjourney's Enterprise API exists but is application-only and inaccessible to individual developers.

Cascade's pluggable-backend design exists in part to give users a sanctioned escape hatch: Flux, DALL-E, Stable Diffusion, and Imagen all have real APIs. If the legal exposure of the MJ backend matters to a given user, the same Cascade installation drives any of those backends with a config change.

This stance lives in `TOS.md`, the README's first paragraph, and the PyPI long description. It is not buried.

---

## 13. Versioning + roadmap

Semantic versioning, independent per package, both starting at `v0.1.0`.

| Version | Headline |
|---|---|
| v0.1 | MJ V7 backend, facet composer, curation, MCP server, AGENTS.md, prompt templates, Python + TS packages |
| v0.2 | Flux via Fal backend, OpenAI gpt-image-1 backend, Windows bridge support |
| v0.3 | Flux Kontext (instruction-edit) backend, Tier 3 bundled binary distribution, vision-loop helpers |
| v0.4 | Imagen 3, Ideogram, Recraft backends, multi-backend prompt strategies |
| v1.0 | API stable for two minor releases without breakage, at least three backends in production, MCP server adopted by a measurable number of agent hosts |

The HTTP contract between the bridge and the client is the load-bearing stability seam. Breaking changes there bump minor for both packages in the same release. The `AssetSpec` shape and `PromptComposer` output format are stable from v0.1.0.

---

## 14. Tone, license, contribution

MIT licensed. `AGENTS.md` and `CONTRIBUTING.md` both stipulate that contributions optimizing for human-developer ergonomics at the expense of LLM-operator ergonomics will be declined — the priority order is the priority order. No emojis in any committed file. No "made with AI" footers in commits, PRs, or any artifact.

The tone of the README, the OPERATIONS doc, and the AGENTS.md is plain, direct, and honest about what works and what doesn't. The runbook's "Sprint 4.0 / 4.7 lessons learned" section ships as part of the public documentation because the failure stories are the most useful onboarding material.

---

## 15. Open questions

1. **Org name on GitHub and npm.** `@cascade/mj-client` assumes a `cascade` org. Fallback to `@cascade-mj/client` under a `cascade-mj` org, or unscoped `cascade-mj`.
2. **PyPI name conflict check.** Verify `cascade-mj` is free before announcement.
3. **Launch venue.** Personal blog, dev.to, or fresh GitHub Pages site under the monorepo.
4. **Initial MCP server registry priority.** Which of `modelcontextprotocol/servers`, `awesome-mcp-servers`, `mcp.so`, Smithery, and Cursor's MCP catalog ships v0.1 listings first.
5. **Whether to ship a `cascade-mj-doctor` subcommand at v0.1** that runs the entire validation suite (env, Discord connection, MJ command version, bridge health, MCP server startup) in one shot. Strongly indicated by the LLM-operator priority; cost is non-trivial.

---

*This spec is the canonical product definition. Update on architectural decisions; the packaging plan and runbook follow from it.*

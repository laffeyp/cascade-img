# Cascade-MJ — Packaging and Public Release Plan

*This document is the plan to take the local Cascade asset pipeline (currently `Cascade/asset_pipeline/mj_bridge.py` + Katybird's `tools/cascade-asset.ts` + `tools/crop-grid.py`) and turn it into two published, installable packages — `cascade-mj` on PyPI and `@cascade/mj-client` on npm — released under one public monorepo, positioned and distributed so other developers actually find and use it. Written 2026-05-26 after the prior-art research pass.*

---

## Primary user: an LLM agent, not a human developer

This needs to be stated up front because it shapes every design decision below: **Cascade is built to be operated by an LLM, not by a human.** The Architect (the human) has not run any of this manually. Every roll fired so far — Sprint 4.0 Wave-1 birds and clues, Sprint 4.7 wing-overlay attempts, the curation steps, the prompt logging, the patches discovered when the bridge silently swallowed jobs — was driven by an LLM Supervisor inside the Katybird loop. The whole point of the project is to close the asset-generation feedback loop *inside* an LLM-run development cycle: the human supplies guidance once (moodboard, character sref, identity-lock reference), and the LLM autonomously composes prompts, fires generations, inspects results, re-rolls, and promotes winners into the project tree, with all of it traceable.

That changes what "packaging" means here. Three concrete consequences:

1. **The CLI is the primary surface, not the library API.** LLMs invoke shell commands reliably and parse stdout. They wire library APIs less reliably. The TypeScript class exports exist for human-written consumer code, but the CLI is the contract that matters for the LLM-run case. Every CLI command takes `--json` and emits a single structured JSON object on stdout, with stderr reserved for human-readable progress.
2. **Errors are structured remediation, not stack traces.** When the bridge is down, the LLM needs to read "bridge unreachable, start it with `cascade-mj-bridge`" — not a Python traceback. Every typed error from `BridgeClient` and every CLI failure prints a JSON object with `code`, `message`, and `remediation` fields. The four real failure modes (bridge down, Discord not ready, MJ command outdated, token expired) each have a code an LLM can branch on.
3. **A third package surface ships: an MCP server.** Model Context Protocol is the cleanest way to hand Cascade to an LLM as a tool. A third console script — `cascade-mj-mcp` — exposes `imagine`, `wait`, `status`, `crop_grid`, `promote`, and `read_prompt_log` as MCP tools, with JSON schemas the LLM can introspect. This is what Claude Desktop, Cursor, and any MCP-aware agent host plug into. For LLM-agent consumers, the MCP server is the *only* integration they need; the CLI and library remain for non-agent consumers.

The feedback loop the LLM has to be able to close, end-to-end, with these three surfaces:

```
guidance (human, once)  →  moodboard ID + character sref + oref reference image
                                              │
                                              ▼
  ┌─────────────────────────────────────────────────────────────┐
  │  LLM loop (per asset):                                      │
  │    compose prompt (subject + style stack + identity stack)  │
  │    fire generation (imagine + wait)                         │
  │    read result PNG with vision                              │
  │    decide: promote / re-roll / escalate ow                  │
  │    crop + alpha-key + promote winner                        │
  │    log the decision to the prompt ledger                    │
  └─────────────────────────────────────────────────────────────┘
```

The package surfaces have to make every step in that loop a single, well-typed call with structured output the LLM can reason over without scraping prose.

---

## What changed because of the research

The research pass found no clean equivalent to Cascade exists, but coverage is uneven across the surface. That changes the positioning, not the shape:

- **TypeScript self-bot drivers** are covered by `erictik/midjourney-api` (npm `midjourney`, 1.8k stars, actively maintained). Cascade's TS package is not a competitor here — it sits one layer up, as a facet-composition and curation orchestrator that happens to talk to the Cascade Python bridge over HTTP. Different layer, different audience.
- **Python self-bot drivers + local HTTP bridge** is genuine whitespace. Every Python project in this slot (`Wildric-Auric/MidJourney-Wrapper`, `ezioruan/midjourney-python-api`, `yachty66/unofficial_midjourney_python_api`) is archived or stale since 2023–2024. The Java equivalent (`novicezk/midjourney-proxy`, 5.3k stars) exists and is active, but Java is the wrong stack for the Python-tool audience this serves.
- **V7 facet composition** (subject + style stack with `--p`/`--sref`/`--s` + identity stack with `--oref`/`--ow`) has zero OSS coverage. Omni-reference is thirteen months old; no package treats it as a first-class composable layer. Paid REST proxies (PIAPI, TheNextLeg, useapi.net) pass raw prompt strings through. This is the differentiator that gets the project read.
- **Curation utilities** (grid-quadrant split, four-corner-average alpha-key, winner promotion, append-only prompt log) only exist as scattered web tools. No package bundles them.

The headline of the public release is therefore "**V7 facet-composition pipeline for Midjourney, with bridge and curation**," not "yet another MJ client." Cascade differentiates on the layer above the network — composition, curation, reproducibility — exactly where the unoccupied ground is.

---

## What gets published

Three artifacts, two packages, one monorepo, one GitHub release cycle. The MCP server lives inside the Python package as a third console script, not as a separate distribution — installing `cascade-mj` gives you the bridge, the curation tools, and the MCP server in one install.

### Package 1 — `cascade-mj` (PyPI)

Python 3.10+. Bundles:
- The patched bridge daemon (current `mj_bridge.py` with the `guild_id` fix and the `_match_grid` fallback for MJ v7 posting the final grid as a new message — both patches that are not upstream anywhere because there is no upstream).
- The thin client (`mj_client.py`).
- A new `cascade_mj.curation` submodule extracting the grid-quadrant cropper, four-corner alpha-key, and promote step from `tools/crop-grid.py`.
- A `.env.example` and a startup-time validator that fails loudly with the exact missing-config message rather than a Discord 400 (the `MJ_GUILD_ID` trap).

Console scripts:
- `cascade-mj-bridge` — start the daemon.
- `cascade-mj-curate` — quadrant crop / alpha-key / promote. `--json` mode for LLM consumers.
- `cascade-mj-mcp` — MCP server exposing `imagine`, `wait`, `status`, `crop_grid`, `promote`, `read_prompt_log` as tools with JSON schemas. Stdio transport (the Claude Desktop / Cursor default); optional `--http` for agent hosts that prefer it.

Runtime dependencies: `discord.py-self`, `flask`, `requests`, `python-dotenv`, `Pillow`. Pinned to ranges that work on Python 3.10–3.13.

### Package 2 — `@cascade/mj-client` (npm)

Pure TypeScript, zero runtime dependencies beyond `node:` built-ins. Exports:
- `BridgeClient` — HTTP wrapper for the Python bridge with the calibrated `/wait` timeout table (grid=180s, single upscale=360s, all=600s) and typed errors for the four real failure modes (bridge down, Discord not ready, MJ command outdated, token expired).
- `PromptComposer` — the central abstraction. Takes a subject + optional style stack + optional identity stack + aspect ratio and emits a v7 prompt string. Style and identity are independently composable.
- `AssetRegistry` — interface only. Consumers supply their own `Record<assetId, AssetSpec>`. The library never owns project-specific data.
- `PromptLog` — append-only markdown ledger with consumer-supplied destination path.

CLI binary: `cascade-mj <assetId> [--upscale grid|1|2|3|4|all] --registry ./assets.{ts,js,json} [--json]`. The `--json` flag makes stdout a single structured object with `status`, `paths`, `prompt`, `job_id`, and `error` (with `code` + `remediation`) — the contract LLM callers parse against. Without it, stdout is human-readable progress.

### What does NOT ship in the packages

- Katybird's `ASSETS` map, moodboard ID, sref URLs, oref bird URL.
- Anything that hardcodes `handoff/cascade-prompts/sprint-4.0.md`.
- Phaser-side wiring instructions.

These move to `examples/katybird/` inside the monorepo as the worked consumer reference. The README points at it.

---

## Monorepo layout

```
cascade-mj/
├── README.md                       # what it is, install, the V7 facet pitch
├── OPERATIONS.md                   # generalized runbook (failure tree, timing, oref escalation, MJ_GUILD_ID gotcha)
├── TOS.md                          # explicit ToS posture (see below)
├── LICENSE                         # MIT
├── CHANGELOG.md                    # per-package changelogs, kept in sync at release
├── pnpm-workspace.yaml
├── package.json                    # workspace root, scripts only
├── packages/
│   ├── mj-bridge/                  # → PyPI: cascade-mj
│   │   ├── pyproject.toml
│   │   ├── src/cascade_mj/
│   │   └── tests/
│   └── mj-client/                  # → npm: @cascade/mj-client
│       ├── package.json
│       ├── src/
│       ├── bin/
│       └── test/
├── examples/
│   └── katybird/                   # the worked consumer reference
└── .github/
    └── workflows/
        ├── ci.yml                  # lint + test both packages
        └── release.yml             # tagged-release publish to both registries
```

---

## Language and tooling decisions

These are the decisions, with the why in one line each.

| Decision | Choice | Why |
|---|---|---|
| Bridge language | Python 3.10+ | `discord.py-self` lives here; the whitespace is Python; PEP 604 syntax is already in the code. |
| Client language | TypeScript | Matches the consumer (Katybird) and the broader gamedev/Phaser audience; ESM-only, Node 20+. |
| Monorepo tool | pnpm workspaces | Lighter than Nx/Turborepo for two packages; native workspace support; no extra config layer. |
| Python build | Hatchling via `pyproject.toml` | Modern PyPA-recommended; no `setup.py`; clean console-script entrypoints. |
| TS build | `tsup` | Zero-config ESM + CJS dual build; bundles the CLI; faster than rolling tsc + esbuild manually. |
| TS test | `vitest` | Native ESM, no transform config, fast. |
| Python test | `pytest` | Standard. |
| Python lint | `ruff` | Single tool covers lint + format + imports. |
| TS lint | `biome` | Single tool covers lint + format; faster than ESLint+Prettier. |
| MCP framework | `mcp` (the official Python SDK from Anthropic) | Stdio + HTTP transports out of the box; the canonical way to ship an MCP server; matches the agent hosts (Claude Desktop, Cursor, Cline) that will be the heaviest consumers. |
| Structured-output schemas | JSON Schema, hand-written, versioned alongside the package | Pydantic models on the Python side double-serve as MCP tool input schemas; TS side declares matching Zod schemas; both are codegen sources of truth for the LLM-readable contract. |
| License | MIT | Matches the audience norm; permissive enough that closed-source consumers (game studios) aren't blocked. |
| Release automation | GitHub Actions + `changesets` for npm + `python -m build && twine upload` for PyPI, both triggered on a tag matching `v*` | One git tag, both packages publish. Independent version numbers fine; `changesets` tracks them. |

---

## ToS posture — explicit

Every Discord-self-bot project that drives Midjourney violates both Discord's and Midjourney's terms of service. There is no workaround as of May 2026 — Midjourney's Enterprise API exists but is application-only and not generally available. Cascade is no exception, and the public release has to be honest about this in `TOS.md`, the README, and the PyPI long description.

The stance, in one paragraph, copy-paste-ready:

> Cascade drives Midjourney through a Discord user account using `discord.py-self`. This is automation of a Discord account, which Discord's Terms of Service prohibit, and automation of Midjourney, which Midjourney's Terms of Service prohibit. Accounts get banned. Use a sacrificial Discord account. This software is published for research, prototyping, and personal use, and not for production deployments. If Midjourney's Enterprise API becomes generally available, a sanctioned backend will be added.

Putting this front-and-center is itself a differentiator. The competitor projects bury it or omit it.

---

## Release readiness checklist (the gating list)

Before `v0.1.0` ships publicly:

- [ ] Both packages build clean from a fresh clone.
- [ ] CI passes on Python 3.10, 3.11, 3.12, 3.13 and Node 20, 22.
- [ ] `cascade-mj-bridge --check-env` validates the `.env` end-to-end and prints the exact remediation step for each missing/wrong value (especially `MJ_GUILD_ID`, the trap from Sprint 4.0). `--json` mode emits the same as structured output.
- [ ] Every CLI command (`cascade-mj`, `cascade-mj-curate`, `cascade-mj-bridge`) supports `--json` and emits the documented structured-error schema on failure with `code` + `remediation` fields.
- [ ] `cascade-mj-mcp` starts cleanly, lists tools, and round-trips an `imagine` → `wait` → `crop_grid` → `promote` sequence against a live bridge.
- [ ] Two MCP-host quickstarts in the README: Claude Desktop `mcp_servers` config block and Cursor `mcp.json` block. Both verified against current versions.
- [ ] OPERATIONS.md contains: install order, the four-failure-mode tree, the `/wait` timeout table, the oref/ow escalation order, the DevTools-enable trick with the correct settings key, the "MJ silently drops version-incompatible parameters" warning, and an "LLM-agent operation" section covering the feedback-loop pattern.
- [ ] README opens with a 60-second quickstart for the *LLM-agent* case (drop the MCP config block into Claude Desktop, ask "generate me a sprite of a small finch"), then the human-developer quickstart, then the V7 facet section.
- [ ] `examples/katybird/` runs end-to-end against the published packages with no edits beyond filling `.env`. Includes an `agent_session.md` transcript showing an LLM driving the full loop for one asset, end to end.
- [ ] TOS.md exists and is linked from the README's first paragraph.
- [ ] LICENSE present.
- [ ] CHANGELOG entry for v0.1.0 with the patch list (`guild_id`, `_match_grid` fallback) credited as Sprint 4.0/4.7 derivations.
- [ ] Both packages reserve their names on PyPI and npm with a 0.0.1 placeholder release before v0.1.0 ships, so squatters can't grab them between announcement and release.

---

## Distribution plan — getting it in front of people

Publishing to PyPI and npm is necessary and not sufficient. The packages have to be findable by the two distinct audiences that have the problem: LLM-agent operators (primary) and human developers (secondary). Five channels, in priority order:

1. **MCP server listings.** The single highest-leverage channel given the primary user. Submit to the canonical MCP server registries: the `modelcontextprotocol/servers` repository's community list, `awesome-mcp-servers`, `mcp.so`, and Smithery's registry if it stabilizes. An MCP-aware agent host's user discovers Cascade by searching "midjourney" or "image generation" in their MCP catalog and adds it to their config. This is the dominant install path for the LLM-agent case and has no equivalent in the prior-art set — none of the surveyed projects ship MCP servers.

2. **A launch post telling the technical story, framed around the LLM-feedback-loop angle.** Not a feature list — the Sprint 4.0 and Sprint 4.7 narrative: the `MJ_GUILD_ID` trap that wasn't in any README, the v7 grid-matching bug that stalled jobs at `progress` forever, the oref single-image vs. grid-URL discovery, the four-corner alpha-key heuristic for "MJ ignores transparent background." The framing: *every one of these was found by an LLM running the loop, not by a human running commands.* This is the post that gets linked from `r/midjourney`, `r/StableDiffusion`, `r/LocalLLaMA`, and Hacker News. Title pattern: "We built a Midjourney V7 pipeline an LLM can actually drive — here's what broke." Publish on a personal blog or `dev.to` (avoid Medium's paywall). Cross-post to Lobsters.

3. **Show HN at launch.** Same day as the blog post. Title pattern: "Show HN: Cascade-MJ — let an LLM agent generate and curate Midjourney V7 assets autonomously." Lead with the LLM-loop angle plus the V7 omni-reference whitespace, not the bridge. First comment from the author: link to TOS.md and the Sprint 4.0 patches, head off the "this violates ToS" thread before it becomes the whole conversation.

4. **Awesome-list submissions.** `awesome-mcp-servers` (the most important one), `awesome-midjourney`, `awesome-generative-ai`, `awesome-discord-bots`, the broader `awesome-python` and `awesome-nodejs`, and `awesome-claude` / `awesome-cursor` style agent-tool lists. Passive but durable — long-tail discovery for years.

5. **Targeted subreddit + Discord posts after the launch wave.** `r/ClaudeAI` and `r/Cursor` (the LLM-agent angle, with a screenshot of the agent driving a roll), `r/midjourney` (the V7 facet angle), `r/gamedev` and `r/IndieDev` (the sprite-art angle, with the Katybird example as the screenshot), `r/Phaser` directly. The Phaser Discord has an `#assets` channel where this is on-topic. Avoid drive-by posts; engage in threads where someone is asking "how do I let my agent generate assets" or "how do I get consistent character sprites" and answer the question, with the package as one option among several.

The LLM-agent + gamedev intersection is the secret weapon. The MJ subreddit is saturated with prompt-engineering posts; the agent-tooling crowd is hungry for non-trivial MCP servers that do real creative work; the gamedev community is starved for usable sprite-asset tooling. Cascade sits exactly at the intersection of all three.

---

## Versioning and maintenance commitment

- Semver, independent per package, both starting at `v0.1.0`.
- The HTTP contract between the bridge and the client is the load-bearing seam. Breaking changes there bump minor for both packages in the same release.
- The `AssetSpec` shape and `PromptComposer` output format are stable from v0.1.0 — these are what consumer code is built against.
- Midjourney command-version bumps (the `MJ_IMAGINE_VERSION` rotation that happens every few weeks) are documented in OPERATIONS, not patched per-release. Users re-capture; the bridge doesn't lie about why it failed.
- Pre-1.0 means breaking changes can happen with a minor bump, called out in CHANGELOG. v1.0 ships when the API has been stable for two minor releases without breakage.

---

## Designing for LLM operation — what this changes concretely

Beyond the surface decisions above (CLI-first, JSON everywhere, MCP server, structured errors), four design rules follow from the LLM-as-operator premise. They go in CONTRIBUTING.md so future contributors don't accidentally optimize for the human-developer case at the LLM-operator case's expense:

1. **Output paths are deterministic and predictable.** An LLM that can read a PNG with vision needs to know the path before the call returns. `cascade-mj <assetId>` writes to a path computable from `assetId` alone — no timestamps, no UUIDs, no nondeterministic suffixes. The MCP `imagine` tool returns the path string explicitly in its response payload regardless.
2. **The prompt log is working memory, not just an audit trail.** The `read_prompt_log` MCP tool returns the last N entries as structured objects (not markdown text), so the LLM can answer "what have I already tried for this asset?" without scraping prose. The append-only contract means an LLM can write its decisions in and read them back without coordination.
3. **Errors carry remediation, not blame.** No error returned to an LLM should be "this is broken." Every error is "this is broken because X; do Y to fix it." The `MJ_GUILD_ID` trap is the worked example: the original failure was Discord 400 + "Unknown Channel" — an LLM cannot recover. The remediated failure is `{"code": "MISSING_GUILD_ID", "remediation": "Add MJ_GUILD_ID to .env; see OPERATIONS.md §setup"}` — the LLM can either fix it or ask the human for that one specific value.
4. **The loop is closeable without human intervention for the common case.** Generate → wait → read PNG → decide → re-roll or promote → log. The only step that *must* be human is the initial guidance setup (one moodboard, one sref, one oref). After that, an unattended agent should be able to produce a curated asset library given a list of `assetId`s and subject descriptions. If a design decision makes this loop require a human-in-the-loop step that isn't the initial guidance, it's the wrong design decision.

---

## What this plan deliberately does not include

- A roadmap for the not-yet-public Midjourney Enterprise API. If it ships generally available, a sanctioned backend gets added behind the same `BridgeClient` interface, no consumer code changes. Until then, no work.
- A drop-in adapter for `erictik/midjourney-api`. The cleaner abstraction is "Cascade speaks to the Cascade bridge"; cross-backend support is a v0.2+ conversation if anyone asks for it.
- A web UI. The package is a library and a CLI. Anything else is a separate project.
- Audio, video, or non-Midjourney image backends. The name is `cascade-mj` for a reason.

---

## Open decisions to resolve before execution

1. **Org name on GitHub and npm.** `@cascade/mj-client` assumes a `cascade` org. If unavailable, fall back to `@cascade-mj/client` under a `cascade-mj` org, or to an unscoped `cascade-mj` (single npm package, less elegant but unblocks).
2. **PyPI name conflict check.** `cascade-mj` looks free as of this writing; verify before announcing.
3. **License confirmation.** MIT is the default above; switch to Apache-2.0 if patent-grant language matters to any future contributor.
4. **Launch post venue.** Personal blog, dev.to, or a fresh GitHub Pages site under the monorepo.

---

*Living document. Update on plan execution; archive when v0.1.0 ships.*

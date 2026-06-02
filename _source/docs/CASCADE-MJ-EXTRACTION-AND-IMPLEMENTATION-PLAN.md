# Cascade-MJ — Extraction and Implementation Plan

*The execution document. How we get from the current state (Cascade pipeline scattered across two private project trees) to v0.1.0 published on PyPI and npm. File-by-file, phase-by-phase, with the non-negotiable safety rule that no existing project gets modified.*

*Companion to `CASCADE-MJ-PRODUCT-SPEC.md` (what to build) and `CASCADE-MJ-PACKAGING-AND-PUBLIC-RELEASE-PLAN.md` (release mechanics). When this doc and either of those disagree, the spec wins.*

*Written 2026-05-26. Living document — update on phase completion; archive when v0.1.0 ships.*

---

## 0. The non-negotiable safety rule

**No file in `/Users/peterlaffey/Documents/Claude/Projects/Katybird/` is modified by this work. No file in `/Users/peterlaffey/Documents/Claude/Projects/Cascade/asset_pipeline/` is modified by this work.** Both projects keep working unchanged throughout the extraction. The new monorepo at `/Users/peterlaffey/Documents/Claude/Projects/cascade-mj/` is the only place files are written.

When extraction needs source from either project, the source is **copied**, then refactored in the new tree. The originals remain.

When the extracted code is verified to work standalone (Phase 6 gates), the originals can optionally be retrofitted in a *separate*, *later* migration to consume the published packages — but that's a follow-on project, not part of this plan, and it requires explicit go-ahead.

---

## 1. Source inventory

Exhaustive list of every file the new package depends on, with current location and role.

### From `/Users/peterlaffey/Documents/Claude/Projects/Cascade/asset_pipeline/`

| File | Lines | Role |
|---|---|---|
| `mj_bridge.py` | 541 | Flask + discord.py-self daemon. Patched twice locally (the `guild_id` fix in `_send_imagine`; the `_match_grid` fallback for MJ v7 grid-as-new-message). |
| `mj_client.py` | 82 | Thin CLI + import helper for the bridge. |
| `.env.example` | small | Config template — needs `MJ_GUILD_ID` added (the Sprint 4.0 trap). |
| `README.md` | 353 | Upstream README; reference material for the new OPERATIONS.md but not copied verbatim. |

### From `/Users/peterlaffey/Documents/Claude/Projects/Katybird/tools/`

| File | Lines | Role | Disposition |
|---|---|---|---|
| `cascade-asset.ts` | 385 | The current TS driver. Bakes Katybird's `ASSETS` map, moodboard, sref URLs, oref. | **Split**: generic mechanics → Python `BridgeClient` / `PromptComposer` / `PromptLog`; Katybird data → `examples/katybird/assets.py` |
| `crop-grid.py` | 240 | Quadrant cropper + four-corner alpha-keyer + asset promoter. Hardcodes Katybird `ALPHA_KEY` map. | **Split**: mechanics → `cascade_mj.curation`; Katybird config → `examples/katybird/curation_config.py` |
| `extract-wings.py` | 130 | Sprint 4.7d wing-overlay extraction helper. Katybird-specific. | **Move to example only**: `examples/katybird/extract_wings.py` |
| `extract-head-feet.py` | 80 | Sprint 4.7e head/feet overlay helper. Katybird-specific. | **Move to example only**: `examples/katybird/extract_head_feet.py` |
| `decode-region-markup.py` | 280 | Region-markup decoder. Unrelated to Cascade. | **Skip** — stays in Katybird. |
| `test-markup-decoder.py` | 160 | Test for the above. | **Skip**. |
| `capture-*.ts`, `screenshot.ts`, `check-vocabulary-parity.ts` | various | Phaser/SDD harness. Unrelated. | **Skip**. |

### From `/Users/peterlaffey/Documents/Claude/Projects/Katybird/handoff/`

| File | Lines | Role | Disposition |
|---|---|---|---|
| `cascade-asset-pipeline-runbook.md` | 421 | The operational runbook — Sprint 4.0 + 4.7 lessons. | **Generalize → `OPERATIONS.md`** in the new monorepo. Strip Katybird-specific paths; keep failure tree, timing table, oref escalation, MJ_GUILD_ID gotcha, DevTools trick, V7-parameter-silently-dropped warning. |
| `cascade-prompts/sprint-4.0.md` | varies | Append-only prompt log for Katybird Wave-1. | **Reference only** — used as the worked example of what a prompt log looks like; not copied. |

### From this repo (the canonical specs)

| File | Role | Disposition |
|---|---|---|
| `CASCADE-MJ-PRODUCT-SPEC.md` | Product canon. | **Copy to** `docs/PRODUCT-SPEC.md` in the new monorepo, with light edits to remove "Katybird repo" framing where appropriate. |
| `CASCADE-MJ-PACKAGING-AND-PUBLIC-RELEASE-PLAN.md` | Release mechanics. | **Copy to** `docs/PACKAGING-AND-RELEASE.md`. |
| `CASCADE-MJ-EXTRACTION-AND-IMPLEMENTATION-PLAN.md` (this file) | Execution plan. | **Copy to** `docs/EXTRACTION-AND-IMPLEMENTATION.md`. |

---

## 2. Destination layout

```
/Users/peterlaffey/Documents/Claude/Projects/cascade-mj/
├── README.md
├── AGENTS.md                       # the LLM-readable entry point
├── OPERATIONS.md                   # generalized runbook
├── TOS.md                          # ToS posture
├── LICENSE                         # MIT
├── CHANGELOG.md
├── CONTRIBUTING.md
├── .gitignore
├── pnpm-workspace.yaml
├── package.json                    # workspace root, scripts only
├── docs/
│   ├── PRODUCT-SPEC.md
│   ├── PACKAGING-AND-RELEASE.md
│   └── EXTRACTION-AND-IMPLEMENTATION.md
├── prompts/                        # bundled system-prompt templates
│   ├── generate-sprite-set.md
│   ├── generate-character-locked-variants.md
│   ├── generate-region-backdrop.md
│   └── refine-existing-asset.md
├── packages/
│   ├── mj-bridge/                  # → PyPI: cascade-mj
│   │   ├── pyproject.toml
│   │   ├── README.md
│   │   ├── src/cascade_mj/
│   │   │   ├── __init__.py
│   │   │   ├── backends/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── base.py         # ImageGenerationBackend abstract
│   │   │   │   ├── midjourney_discord/
│   │   │   │   │   ├── __init__.py
│   │   │   │   │   ├── bridge.py   # the daemon (from mj_bridge.py)
│   │   │   │   │   └── client.py   # thin client (from mj_client.py)
│   │   │   │   └── capabilities.py
│   │   │   ├── composer.py         # PromptComposer + facet types
│   │   │   ├── client.py           # BridgeClient (backend-agnostic)
│   │   │   ├── curation/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── crop_grid.py
│   │   │   │   ├── alpha_key.py
│   │   │   │   └── promote.py
│   │   │   ├── log.py              # PromptLog
│   │   │   ├── errors.py           # typed errors + remediation
│   │   │   ├── schemas.py          # Pydantic models, JSON Schema export
│   │   │   ├── cli/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── main.py         # cascade-mj
│   │   │   │   ├── bridge.py       # cascade-mj-bridge (with --check-env, --doctor)
│   │   │   │   ├── curate.py       # cascade-mj-curate
│   │   │   │   └── mcp_server.py   # cascade-mj-mcp
│   │   │   └── mcp/
│   │   │       ├── __init__.py
│   │   │       ├── server.py
│   │   │       └── tools.py
│   │   ├── tests/
│   │   │   ├── test_composer.py
│   │   │   ├── test_curation.py
│   │   │   ├── test_log.py
│   │   │   ├── test_errors.py
│   │   │   ├── test_schemas.py
│   │   │   └── integration/
│   │   │       └── test_bridge_smoke.py
│   │   └── .env.example
│   └── mj-client/                  # → npm: @cascade/mj-client
│       ├── package.json
│       ├── tsconfig.json
│       ├── README.md
│       ├── src/
│       │   ├── index.ts
│       │   ├── bridge-client.ts    # spawns Python CLI or hits bridge HTTP
│       │   ├── prompt-composer.ts  # mirrors Python composer
│       │   ├── types.ts            # Zod schemas matching Pydantic
│       │   ├── errors.ts
│       │   └── mcp-server.ts       # optional Node-native MCP server
│       ├── bin/
│       │   └── cascade-mj.ts       # CLI shim
│       ├── scripts/
│       │   └── postinstall.ts      # Tier 2: install Python engine via uv
│       └── test/
├── examples/
│   └── katybird/
│       ├── README.md               # how to wire Cascade for the Katybird pattern
│       ├── assets.py               # the ASSETS map from cascade-asset.ts, in Python
│       ├── curation_config.py      # the ALPHA_KEY map from crop-grid.py
│       ├── extract_wings.py        # Sprint 4.7d helper (verbatim)
│       ├── extract_head_feet.py    # Sprint 4.7e helper (verbatim)
│       └── agent_session.md        # transcript of an LLM driving Cascade end-to-end
└── .github/
    └── workflows/
        ├── ci.yml                  # lint + test, Python 3.10-3.13 × Node 20/22
        └── release.yml             # tagged release → PyPI + npm
```

---

## 3. Migration matrix

Every source file's fate, in one place. **Action** column: `COPY` = verbatim or near-verbatim, `EXTRACT` = pull out generic pieces and refactor, `WRITE` = no source exists, must be authored, `REFERENCE` = read but not copied.

| Source | Destination | Action | Notes |
|---|---|---|---|
| `Cascade/.../mj_bridge.py` | `packages/mj-bridge/src/cascade_mj/backends/midjourney_discord/bridge.py` | EXTRACT | Keep both patches (`guild_id`, `_match_grid`). Restructure module-level globals into a config dataclass. Replace direct env reads with the config object. Add structured logging. |
| `Cascade/.../mj_client.py` | `packages/mj-bridge/src/cascade_mj/backends/midjourney_discord/client.py` | COPY | Light cleanup; rename CLI entry to internal helper since the new `cascade-mj-bridge` CLI replaces it. |
| `Cascade/.../.env.example` | `packages/mj-bridge/.env.example` | COPY+EDIT | Add `MJ_GUILD_ID` with the Sprint 4.0 explanation comment. |
| `Cascade/.../README.md` | — | REFERENCE | Informs OPERATIONS.md. Not copied. |
| `Katybird/tools/cascade-asset.ts` (prompt-build + bridge HTTP + log) | `packages/mj-bridge/src/cascade_mj/{composer.py, client.py, log.py}` | EXTRACT | Port the TS logic to Python. Three separable concerns become three files. |
| `Katybird/tools/cascade-asset.ts` (ASSETS map, sref URLs, OREF_BIRD, MOODBOARD) | `examples/katybird/assets.py` | EXTRACT | The project-specific data lands in the example. |
| `Katybird/tools/crop-grid.py` (cropper + alpha + promote) | `packages/mj-bridge/src/cascade_mj/curation/{crop_grid.py, alpha_key.py, promote.py}` | EXTRACT | Split the three concerns into three modules. |
| `Katybird/tools/crop-grid.py` (ALPHA_KEY map, source-path conventions) | `examples/katybird/curation_config.py` | EXTRACT | Project-specific mapping out of library code. |
| `Katybird/tools/extract-wings.py` | `examples/katybird/extract_wings.py` | COPY | Sprint 4.7d helper; demonstrates a layered-overlay pattern other consumers might want. |
| `Katybird/tools/extract-head-feet.py` | `examples/katybird/extract_head_feet.py` | COPY | Same. |
| `Katybird/handoff/cascade-asset-pipeline-runbook.md` | `OPERATIONS.md` | EXTRACT | Strip Katybird paths, keep all operational knowledge. |
| (this repo) `CASCADE-MJ-PRODUCT-SPEC.md` | `docs/PRODUCT-SPEC.md` | COPY+EDIT | Light reframing where the doc refers to "this repo." |
| (this repo) `CASCADE-MJ-PACKAGING-AND-PUBLIC-RELEASE-PLAN.md` | `docs/PACKAGING-AND-RELEASE.md` | COPY | |
| (this repo) `CASCADE-MJ-EXTRACTION-AND-IMPLEMENTATION-PLAN.md` | `docs/EXTRACTION-AND-IMPLEMENTATION.md` | COPY | |
| — | `packages/mj-bridge/src/cascade_mj/backends/base.py` | WRITE | Abstract `ImageGenerationBackend` base class — the pluggable seam. |
| — | `packages/mj-bridge/src/cascade_mj/backends/capabilities.py` | WRITE | `BackendCapabilities` dataclass: facets supported, max ar, latency band. |
| — | `packages/mj-bridge/src/cascade_mj/errors.py` | WRITE | Typed error classes; remediation strings; the four MJ failure codes. |
| — | `packages/mj-bridge/src/cascade_mj/schemas.py` | WRITE | Pydantic models for everything cross-surface; JSON Schema export for MCP. |
| — | `packages/mj-bridge/src/cascade_mj/mcp/{server.py, tools.py}` | WRITE | MCP server. Imagine, wait, status, crop_grid, alpha_key, promote, read_prompt_log, compose_prompt, list_backends. |
| — | `packages/mj-bridge/src/cascade_mj/cli/bridge.py` (with `--check-env`, `--doctor`) | WRITE | New CLI subcommands that don't exist today. |
| — | `packages/mj-client/**` | WRITE | The TypeScript wrapper. Tier 2 (postinstall `uv tool install`) at v0.1. |
| — | `AGENTS.md` | WRITE | The LLM-readable entry point. |
| — | `prompts/*.md` | WRITE | Four bundled system-prompt templates. |
| — | `TOS.md` | WRITE | The honest ToS posture from the spec. |
| — | `examples/katybird/agent_session.md` | WRITE | A real transcript of an LLM driving Cascade for one asset, end to end. Captured live during Phase 6. |
| — | `.github/workflows/{ci.yml, release.yml}` | WRITE | Standard release engineering. |

---

## 4. Phases

Seven phases. Each phase has a gate — explicit, testable, no ambiguity about "done."

### Phase 1 — Scaffold

Goal: empty monorepo with workspace tooling and license, no code yet.

Steps:
1. `mkdir -p /Users/peterlaffey/Documents/Claude/Projects/cascade-mj`
2. `git init`. Commit the empty repo.
3. Write `LICENSE` (MIT), `.gitignore` (Python + Node + IDE noise), `pnpm-workspace.yaml`, root `package.json` with workspace scripts only.
4. Create the empty directory skeleton matching section 2.
5. Copy the three canonical docs from this repo to `docs/`.

Gate: `pnpm install` runs clean. `git log` shows one initial commit.

### Phase 2 — Copy verbatim (no refactor)

Goal: every COPY-marked file from the migration matrix lands at its destination unchanged. Project still doesn't build, but every external file is now in the new tree.

Steps:
1. Copy `mj_client.py` → `packages/mj-bridge/src/cascade_mj/backends/midjourney_discord/client.py`.
2. Copy `mj_bridge.py` → same directory as `bridge.py` (rename). Do not refactor yet.
3. Copy `.env.example` → `packages/mj-bridge/.env.example`. Add the `MJ_GUILD_ID` line with comment.
4. Copy `extract-wings.py` and `extract-head-feet.py` → `examples/katybird/`.
5. Commit: "phase 2: verbatim copy of existing sources."

Gate: every file in the migration matrix marked COPY exists at its destination. `diff` against source shows zero changes for COPY entries, only the explicit edits for COPY+EDIT entries.

### Phase 3 — Extract with refactor

Goal: split the existing files into the new module layout. The pluggable backend interface gets introduced here.

Steps:
1. Write `backends/base.py` — the `ImageGenerationBackend` abstract class — first, so the refactor target is real.
2. Write `backends/capabilities.py` — `BackendCapabilities` dataclass.
3. Refactor `backends/midjourney_discord/bridge.py`: extract the config dataclass, replace module globals, leave both patches untouched.
4. Wrap the MJ bridge daemon in a `MidjourneyDiscordBackend` class that conforms to `ImageGenerationBackend`. The daemon stays the daemon; the class is a thin wrapper.
5. Port `cascade-asset.ts` to Python:
   - Prompt-building logic → `composer.py` with `Subject`, `StyleStack`, `IdentityStack`, `AspectRatio` types and a `PromptComposer` class.
   - HTTP client logic → `client.py` with `BridgeClient` class.
   - Prompt-log writer → `log.py` with `PromptLog` class.
6. Split `crop-grid.py` into three: `curation/crop_grid.py`, `curation/alpha_key.py`, `curation/promote.py`. Pillow becomes an explicit dependency.
7. Move the Katybird-specific `ASSETS` map into `examples/katybird/assets.py` as a `KATYBIRD_ASSETS` Python dict.
8. Move the Katybird-specific `ALPHA_KEY` map into `examples/katybird/curation_config.py`.
9. Write `pyproject.toml`: project metadata, deps (`discord.py-self`, `flask`, `requests`, `python-dotenv`, `Pillow`, `pydantic`, `mcp`), Python 3.10+, the four console scripts.
10. Write unit tests for `composer.py`, `curation/*`, `log.py`. No live MJ calls yet.

Gate: `pytest packages/mj-bridge/tests/` passes. `pip install -e packages/mj-bridge` succeeds. `python -c "from cascade_mj import BridgeClient, PromptComposer"` succeeds. The Katybird `ASSETS` map is reachable from `examples.katybird.assets`.

### Phase 4 — Write the new things

Goal: everything the spec mandates that doesn't exist yet.

Steps:
1. `errors.py` — `BridgeUnreachableError`, `DiscordNotReadyError`, `MJCommandOutdatedError`, `MJTokenExpiredError`, `MissingGuildIdError`, plus a base `CascadeError` with `code` and `remediation` properties. Each error includes a stable `code` string and a human-readable remediation pointing at OPERATIONS.md sections.
2. `schemas.py` — Pydantic models for every cross-surface type: `AssetSpec`, `PromptComposition`, `JobRecord`, `BackendCapabilities`, `ErrorPayload`. Hook up `model_json_schema()` export so MCP tool definitions derive from them.
3. CLI work:
   - `cli/main.py` — `cascade-mj <asset_id> [--upscale ...] --registry <path> [--json]`. Loads a Python or JSON registry file, composes prompt, fires roll, logs, exits.
   - `cli/bridge.py` — `cascade-mj-bridge [start|--check-env|--doctor]`. The `--check-env` validates every required env var with structured remediation. The `--doctor` runs the full validation suite (env, Discord connectable, MJ command version current, bridge starts and reaches healthy state, MCP server starts) in one shot.
   - `cli/curate.py` — `cascade-mj-curate {crop|alpha-key|promote} <asset_id> [...] [--json]`.
   - `cli/mcp_server.py` — entry point for `cascade-mj-mcp`.
4. MCP server (`mcp/server.py` + `mcp/tools.py`):
   - Use the official `mcp` Python SDK.
   - Stdio transport by default; `--http` for HTTP.
   - Tools: `imagine`, `wait`, `status`, `crop_grid`, `alpha_key`, `promote`, `read_prompt_log`, `compose_prompt`, `list_backends`, `set_backend`, `check_env`, `doctor`. Each derives its input schema from the corresponding Pydantic model.
5. Agent-readiness assets:
   - `AGENTS.md` — written from scratch. Sections: what Cascade is, the loop pattern, the tool surface, the failure modes with remediation, the facet semantics, the curation flow, how to ask the human for help when stuck.
   - `prompts/generate-sprite-set.md`, `prompts/generate-character-locked-variants.md`, `prompts/generate-region-backdrop.md`, `prompts/refine-existing-asset.md` — bundled system-prompt templates with placeholders for the human's guidance.
6. `OPERATIONS.md` — port the Katybird runbook with paths generalized. Keep every operational lesson. Add a new "LLM-agent operation" section covering the loop pattern, the structured-error contract, and the `--doctor` workflow.
7. `TOS.md` — the spec's section 12 verbatim.
8. `README.md` — opens with the MCP quickstart for Claude Desktop / Cursor / Cline, then the human CLI quickstart, then the facet section, then the comparison table from spec §10, then the ToS link.
9. `CHANGELOG.md` with the v0.1.0 entry.
10. `CONTRIBUTING.md` with the LLM-priority rule.

Gate: `cascade-mj-bridge --doctor` exits 0 in a clean environment with valid `.env`. `cascade-mj-mcp` starts, lists all tools, and round-trips a `compose_prompt` call. `cascade-mj <asset_id> --json --dry-run` emits the structured-prompt object without firing a roll. All unit tests pass.

### Phase 5 — TypeScript wrapper

Goal: `npm install @cascade/mj-client` lands a working tool.

Steps:
1. `packages/mj-client/package.json` with `bin: cascade-mj`, `postinstall: tsx scripts/postinstall.ts`.
2. `scripts/postinstall.ts`: detect `uv`, fall back to `pipx`, install `cascade-mj` of the matching version. Clear remediation on failure.
3. `src/bridge-client.ts`: HTTP client mirroring the Python `BridgeClient`, or `child_process.spawn` of `cascade-mj --json` — pick one based on Phase 4 ergonomics review.
4. `src/prompt-composer.ts`: TypeScript mirror of the Python composer. Zod schemas matching the Pydantic models.
5. `src/types.ts`: Zod schemas auto-generated from the Pydantic `model_json_schema()` exports, with a sync check in CI.
6. `src/errors.ts`: typed error classes mirroring Python.
7. `src/mcp-server.ts`: optional Node-native MCP server using the TS MCP SDK, for hosts that prefer Node-spawned servers.
8. `bin/cascade-mj.ts`: thin CLI shim that delegates to the Python CLI.
9. `tsup` config for ESM + CJS dual build. `vitest` for tests. `biome` for lint+format.
10. Tests: schema-sync check; spawn-and-parse round-trips against a mocked bridge.

Gate: `npm install @cascade/mj-client` in a clean directory (after publishing to a local Verdaccio for testing) installs cleanly. `npx cascade-mj --help` works. The TS-side Zod schemas pass the sync check against the Python-side JSON schemas.

### Phase 6 — Validation gates (the release readiness checklist)

Goal: every item from spec §release-readiness passes. This is the gate to publishing.

Required:
- [ ] Both packages build from a fresh clone.
- [ ] CI passes on Python 3.10, 3.11, 3.12, 3.13 and Node 20, 22.
- [ ] `cascade-mj-bridge --check-env` and `--doctor` work as specified.
- [ ] Every CLI command supports `--json` with the documented error schema.
- [ ] `cascade-mj-mcp` round-trips an `imagine` → `wait` → `crop_grid` → `promote` sequence against a live bridge.
- [ ] Claude Desktop and Cursor MCP config blocks documented and verified.
- [ ] OPERATIONS.md complete.
- [ ] README's MCP-first and CLI-first quickstarts both work end-to-end.
- [ ] `examples/katybird/agent_session.md` exists — a real transcript of an LLM driving the full loop for one asset against the published packages, captured live as part of this phase.
- [ ] TOS.md present and linked from README's first paragraph.
- [ ] LICENSE present.
- [ ] CHANGELOG entry for v0.1.0.
- [ ] Both package names reserved on PyPI and npm with 0.0.1 placeholder releases.

Optional but recommended:
- [ ] AGENTS.md reviewed by an LLM (literally — feed it AGENTS.md and ask "could you operate Cascade given only this?").
- [ ] Comparison table from spec §10 included in README.

### Phase 7 — Launch

Goal: v0.1.0 in front of the audiences from spec §4.

Steps:
1. Tag `v0.1.0`. Release workflow publishes to both registries.
2. Publish the launch blog post (LLM-feedback-loop angle, Sprint 4.0/4.7 patches as narrative).
3. Show HN same day. First comment links TOS.md.
4. Submit to MCP server registries: `modelcontextprotocol/servers`, `awesome-mcp-servers`, `mcp.so`, Smithery.
5. Submit to `awesome-midjourney`, `awesome-generative-ai`, `awesome-discord-bots`.
6. Targeted posts to `r/ClaudeAI`, `r/Cursor`, `r/midjourney`, `r/gamedev`, `r/Phaser`.
7. Monitor issues. Triage the first wave fast — first-week response time sets the project's reputation.

Gate: v0.1.0 installable from both registries by a stranger with no insider knowledge.

---

## 5. Safety throughout

- The Katybird and Cascade repos are read-only for the duration of this work. Verify with `git -C /Users/peterlaffey/Documents/Claude/Projects/Katybird status` and `git -C /Users/peterlaffey/Documents/Claude/Projects/Cascade status` showing no new uncommitted changes attributable to this work.
- Every phase commits to the new `cascade-mj` repo separately. If a phase needs to be undone, `git reset` to the previous phase's commit; no impact on the originals.
- Phase 2's verbatim copies are diff-verified against source. Phases 3–5 work only on the copies.
- The published v0.1.0 is the first artifact that any external party sees. Until then, nothing leaks.

---

## 6. Open execution decisions

Decisions to surface to the human before the corresponding phase starts. Each is genuinely a decision-only-the-human-can-make.

1. **PyPI and npm name availability.** Verify `cascade-mj` on PyPI and `@cascade/mj-client` on npm before Phase 1. Fallbacks in spec §15.
2. **Branch protection.** Should `main` be branch-protected from day one, or open until v0.1.0 ships?
3. **Author identity on PyPI / npm.** Personal handle, or new project handle (`cascade-mj` bot account)?
4. **Whether to fork `Cascade/asset_pipeline/mj_bridge.py` from the existing local copy or from a clean state.** The local copy has the two patches; a clean state requires re-applying them. The local-copy path is recommended (it's already validated in production).
5. **Whether to ship Tier 3 (bundled PyInstaller binary) at v0.1 or wait until v0.3.** Spec says v0.3; this plan follows the spec. The decision could be revisited after Phase 5 if Tier 2 friction looks bad in practice.

---

## 7. What this plan deliberately does not include

- Backend implementations beyond `MidjourneyDiscordBackend`. Flux, DALL-E, etc. are spec v0.2+ items. The base class lands in v0.1; the second backend lands in v0.2.
- The Katybird retrofit (making Katybird consume the published packages instead of its local copies). Out of scope. Belongs to a follow-on plan after v0.1.0 ships.
- A web UI, a hosted SaaS, audio/video backends. Spec non-goals.
- Migrating `decode-region-markup.py`, `capture-*.ts`, or any other Katybird tooling that isn't Cascade. Stays where it is.

---

*This is the execution plan. Update on phase completion. The product spec governs what to build; this governs how to build it without breaking what already works.*

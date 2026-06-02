# WORKING_AGREEMENT.md — cascade-img

*Per-project overrides and additions on top of `sdd-kit-2/AGENTS.md`. The Agent reads AGENTS.md first (the methodology) and then this file (the project specifics). When the two conflict, AGENTS.md wins — this file augments, it doesn't override the methodology's hard rules.*

---

## Project identity

- **Project name:** cascade-img
- **Project type:** Python package (`cascade-img` on PyPI) + TypeScript wrapper (`@greenrosesystems/cascade-img` on npm) + console scripts + MCP server
- **Primary language(s):** Python 3.10+. TypeScript wrapper at v0.2 target.
- **Adopted SDD kit version:** `sdd-kit-2` (copied into `sdd-kit-2/` at project root, 2026-06-02)
- **Repository:** https://github.com/greenrosesystems/cascade-img
- **Published by:** Green Rose Systems LLC, https://greenrosesystems.com

---

## Project scope (from BLACKBOARD ## Decisions, 2026-06-02)

> cascade-img is a Python package and MCP server that lets an LLM agent generate, curate, and log Midjourney images autonomously through a Discord self-bot bridge. v0.1 ships the MJ backend; v0.2+ adds Flux / DALL-E / Imagen / other sanctioned APIs behind the same `ImageGenerationBackend` interface. Primary user is an LLM agent; secondary is sprite artists / indie devs; tertiary is application developers calling the library. Published under Green Rose Systems LLC. MIT license. ToS posture is honest about the self-bot; pluggable backend is the sanctioned escape.

---

## Canonical home registry

*Per AGENTS.md hard rule 7. Which file owns which public type.*

| Type / module | Canonical home |
|---|---|
| `Config`, `MissingEnvError` | `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` |
| `Job`, `Status`, Flask `app` (the daemon) | same file |
| `MidjourneyDiscordBackend`, `MIDJOURNEY_DISCORD_CAPABILITIES` | `packages/engine/src/cascade_img/backends/midjourney_discord/backend.py` |
| `ImageGenerationBackend`, `BackendCapabilities` | `packages/engine/src/cascade_img/backends/base.py` |
| `PromptComposer`, `Subject`, `StyleStack`, `IdentityStack` | `packages/engine/src/cascade_img/composer.py` |
| `PromptLog` | `packages/engine/src/cascade_img/log.py` |
| `crop_quadrant` | `packages/engine/src/cascade_img/curation/crop_grid.py` |
| `alpha_key_corners` | `packages/engine/src/cascade_img/curation/alpha_key.py` |
| `promote` | `packages/engine/src/cascade_img/curation/promote.py` |
| `emit`, `snapshot`, `clear`, `flush_to_file`, `format_for_ai`, `assert_signal`, `assert_no_signal`, `SignalEmitter`, `SignalVocabulary`, `Signal`, `capture` | `packages/engine/src/cascade_img/instrumentation/sdd.py` |
| MCP server tools (`compose_prompt`, `imagine`, `wait`, `status`, `bridge_health`, `crop_grid`, `alpha_key`, `promote`, `log_append`, `read_prompt_log`) | `packages/engine/src/cascade_img/mcp_server.py` |
| `AssetEntry`, `load_registry` | `packages/engine/src/cascade_img/cli/registry.py` |
| `cascade-mj` CLI entrypoint | `packages/engine/src/cascade_img/cli/mj.py` |

When a sprint surfaces a "where does this type live" question, the Architect's answer goes here.

---

## External SDK bridge mappings

*Per AGENTS.md hard rule on `bridge_mapping_required` halt.*

### `discord.py-self`

- **Package URL:** https://github.com/dolfies/discord.py-self
- **Critical API surface:**
  - `discord.Client()` — the self-bot client.
  - `@client.event` decorators register `on_ready`, `on_message`, `on_message_edit` handlers.
  - `client.ws.session_id` carries the Discord WebSocket session ID required for interaction payloads.
  - `client.start(token)` is the coroutine that drives the WebSocket; runs on a background asyncio loop.
- **Interaction API surface (Discord HTTP, v9):**
  - `POST /api/v9/interactions` with payload `{type: 2 (slash command) | 3 (button), application_id, channel_id, session_id, data, guild_id?}`.
  - The `guild_id` field is REQUIRED when the channel lives in a guild. Sprint 4.0 patch documents this; `MJ_GUILD_ID` env var carries the value.

### Midjourney bot

- **Bot ID:** `936929561302675456` (constant).
- **Slash command:** `/imagine` with `data.version` (rotated every few weeks) and `data.id` (`938956540159881230` stable as of 2026-06).
- **Grid behavior (V7):** the completed grid posts as a NEW message rather than editing the original — Sprint 4.0 patch's `_match_grid` PROGRESS-state fallback handles this.
- **Upscale buttons:** `MJ::JOB::upsample::{1-4}::{mj_job_uuid}` custom_id format on message components.

### Anthropic `mcp` Python SDK

- **Package URL:** https://github.com/modelcontextprotocol/python-sdk
- **Critical API surface:** `from mcp.server.fastmcp import FastMCP`. `FastMCP("name")`, then `@mcp.tool()` decorators. `mcp.run()` for stdio transport; `mcp.run_sse_async(host, port)` for HTTP transport.

---

## Vocabulary discipline overrides

- **Vocabulary location:** Canonical at project root `signals/0.1.json`; bundled copy at `packages/engine/src/cascade_img/signals/versions/0.1.json` (the package-data canonical that ships in the wheel). The two are kept identical; the CI parity step reads the package-data copy.
- **Validator-extras posture:** strict (default). Payload fields not declared in the schema raise. Production may relax via `CASCADE_STRICT_SIGNALS=false`.
- **View-payload-universal convention:** N/A — no UI in cascade-img. The `view` category does not exist in the v0.1 vocabulary.
- **Parity gate command:** `python3 packages/engine/tools/check_vocabulary_parity.py` (run from `packages/engine/`).

---

## Build and verification commands

- **Build:** `python3 -m build` (from `packages/engine/`) — produces sdist + wheel in `dist/`. Exit 0.
- **Install:** `pip install "dist/cascade_img-<version>-py3-none-any.whl[dev]"` (into a fresh venv). Exit 0.
- **Parity:** `python3 tools/check_vocabulary_parity.py` (from `packages/engine/`). Exit 0.
- **Tests:** `pytest tests/` (from `packages/engine/`). Exit 0.
- **Lint:** `ruff check src/ tests/ tools/` (from `packages/engine/`). Exit 0. Optional at the moment.
- **CLI smoke:** `cascade-mj-bridge --doctor` returns `{"ok": true, ...}` when the operator's `.env` is correctly captured.

The Architect (human) runs these commands when grading; the Agent runs them inside the bash sandbox during the discipline ladder.

---

## ToS posture for player-facing strings

This project does not have player-facing strings in the traditional sense, but it DOES carry user-visible strings in two places that need tonal discipline:

- **Error remediations.** Every `MissingEnvError.remediation` is read by an LLM operator or a human; voice is direct, specific, and points at OPERATIONS.md sections. No marketing, no hedging.
- **README / OPERATIONS / AGENTS.** Plain, direct, honest about what works and what doesn't. The Sprint 4.0/4.7 patches are documented as worked-failure narratives because the failure stories are the best onboarding material.

---

## Sprint cadence policy

- **Phase 0 — Vocabulary Session:** locked retroactively for v0.1 (2026-06-02). Future vocabulary evolution runs the supervised-grammar-evolution proposal taxonomy.
- **Phase 1 — v0.1.0a1 port:** complete (Sprint 001, closed 2026-06-02). Ran in collapsed-monolithic mode against kit hard rule 6; flagged on the drift watchlist.
- **Phase 2 — Kit alignment + v0.1.0 finalization:** **plan-mode-per-sprint** until the kit's discipline is internalized. Currently in this phase with Sprint 002 (closed 2026-06-02).
- **Phase 3 — TypeScript wrapper + live-fire smoke + v0.1.0 release:** TBD, depends on Architect cadence preference.

---

## Project-specific halt conditions

- `live_fire_smoke_required` — fires when a sprint card asserts behavior against the running daemon but the daemon hasn't been smoke-tested against real Discord/MJ. Resume: Architect runs the daemon with their `.env` and reports the captured signal trace.

---

## Drift surface log

- **DS-1.** Backend-specific vs package-level naming. Backend-tagged scripts (`cascade-mj-bridge`) only when the backend genuinely needs a unique daemon; package-level scripts (`cascade-mcp`) for surfaces that are backend-agnostic. Mitigation: audit script names at every new backend addition.

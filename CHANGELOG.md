# Changelog

All notable changes to cascade-img are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic versioning per [semver.org](https://semver.org/).

## [Unreleased]

## [0.1.0a1] — 2026-06-02

Initial alpha. Ports the Cascade asset pipeline from the demo's working code into a standalone package under Green Rose Systems.

### Added

- **Bridge daemon** (`cascade_img.backends.midjourney_discord.bridge`)
  - Flask + `discord.py-self` daemon listening on `http://127.0.0.1:5000`.
  - `Config` dataclass and `Config.from_env()` with structured `MissingEnvError` (code + remediation) for each required var.
  - Both the default production patches preserved:
    - `guild_id` field threaded into the `/imagine` interaction payload — fixes Discord 400 "Unknown Channel" when the MJ channel lives in a guild.
    - `_match_grid` PROGRESS-state fallback path — catches MJ V7's grid-as-new-message behavior. Emitted `GRID_MATCHED.match_path` surfaces which path fired.
  - Stable error codes mapped from Discord failure modes: `DISCORD_400_OUTDATED`, `DISCORD_400_UNKNOWN_CHANNEL`, `DISCORD_401`, `GRID_DOWNLOAD_FAILED`, `MJ_UUID_MISSING`, `SUBMIT_FAILED`, `UPSCALE_DOWNLOAD_FAILED`.
  - Console script: `cascade-mj-bridge` with `--check-env` and `--doctor` subcommands returning JSON.

- **Backend interface** (`cascade_img.backends.base`)
  - `ImageGenerationBackend` abstract class — the pluggable seam.
  - `MidjourneyDiscordBackend` thin HTTP wrapper conforming to the interface.
  - `BackendCapabilities` declares facets and supported aspect ratios.

- **Composer** (`cascade_img.composer`)
  - `PromptComposer.compose(Subject, StyleStack, IdentityStack, aspect_ratio)` → MJ V7 prompt string.
  - First-class V7 facets: `--p` (moodboard), `--sref`, `--s` (stylize), `--style raw`, `--oref`, `--ow`, `--ar`.

- **Curation kit** (`cascade_img.curation`)
  - `crop_quadrant(src, quadrant)` — pull one of four 2x2 grid panels (0 = whole image for single-upscale passthrough).
  - `alpha_key_corners(img, tolerance=40)` — four-corner-average background detection and alpha keying.
  - `promote(src, dest)` — copy curated asset to the consumer's asset tree.

- **Prompt log** (`cascade_img.log`)
  - `PromptLog` — append-only JSONL ledger with `read(n=...)` for agent working memory.
  - `render_markdown()` for human review.

- **MCP server** (`cascade_img.mcp_server`)
  - Console script: `cascade-mcp`. Stdio by default; `--http <port>` for HTTP transport.
  - Ten tools: `compose_prompt`, `imagine`, `wait`, `status`, `bridge_health`, `crop_grid`, `alpha_key`, `promote`, `log_append`, `read_prompt_log`.
  - Structured envelope: `{ok, result}` on success, `{ok: false, error: {code, message, remediation?}}` on failure.

- **Unified CLI** (`cascade_img.cli.mj`)
  - Console script: `cascade-mj <asset_id> --registry <path> [--upscale ...] [--dry-run] [--pretty]`.
  - Loads a JSON registry, composes the prompt, fires, waits, logs. JSON to stdout.

- **the event system instrumentation** (`cascade_img.instrumentation.runtime`)
  - `emit`, `snapshot`, `clear`, `flush_to_file` — the runtime contract.
  - Locked vocabulary v0.1 at `cascade_img/signals/versions/0.1.json` with 27 tags across 11 categories (session, config, bridge, job, discord, backend, curation, composer, log, mcp, cli).
  - Parity tool at `tools/check_vocabulary_parity.py` asserts every `emit()` callsite uses a vocabulary tag.

- **Documentation**
  - `README.md`, `OPERATIONS.md` (generalized runbook), `TOS.md`, `AGENTS.md`, four `prompts/*.md` system-prompt templates.

- **Tests**
  - 48 behavior-contract cases under `packages/engine/tests/` covering Config (negative + positive paths), curation (crop quadrant integrity, alpha-key tolerance, promote), composer (all facet combinations), log (append/read roundtrip, render), MCP server (tool envelope + signals), CLI (registry load, dry-run flow, structured errors), and parity-as-test.

### Known limits

- MJ-only backend; Flux, DALL-E, Imagen scheduled for v0.2+.
- Bridge tracks jobs in memory; restart drops in-flight state.
- `JOBS` dict has no eviction or TTL — long-running daemon leaks memory proportional to total jobs run. Acceptable for single-operator sessions; v0.2 adds LRU + TTL + `JOB_EVICTED` signal.
- `/wait` holds one Flask thread per pending request. Concurrent `cascade-mj --upscale all` calls can exhaust the thread pool. v0.2 switches to SSE long-poll or callback-based wait.
- `MidjourneyDiscordBackend.imagine/wait/status/health` are `async def` but call `requests` synchronously; concurrent MCP tool calls serialize. v0.2 ports to `httpx.AsyncClient`.
- macOS and Linux only; Windows bridge is a v0.2 item.
- No webhook support; clients long-poll `/wait`.
- **TypeScript wrapper is a v0.2 deliverable.** The `@greenrosesystems/cascade-img` 0.0.1 placeholder on npm reserves the name. v0.1 is a Python-only ship — Node consumers should wait for v0.2 or call the bridge daemon's HTTP API directly.

[0.1.0a1]: https://github.com/greenrosesystems/cascade-img/releases/tag/v0.1.0a1

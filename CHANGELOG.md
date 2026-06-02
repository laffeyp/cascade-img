# Changelog

All notable changes to cascade-img are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic versioning per [semver.org](https://semver.org/).

## [Unreleased]

### Bridge resilience

- **Discord WebSocket reconnect loop.** `_run_discord` is wrapped in an outer retry loop with exponential backoff (2s → 4 → 8 → 16 → 32 → 60s cap). Transient disconnects emit `DISCORD_DISCONNECTED` then `DISCORD_RECONNECTING` and retry until reconnection succeeds. Auth failures (`discord.LoginFailure`, HTTP 401) emit `DISCORD_RECONNECT_FAILED(reason="auth")` and terminate the loop without burning Discord rate limit. Shutdown is observed via `_shutdown_event` so SIGINT/SIGTERM cuts the backoff sleep short and emits `DISCORD_RECONNECT_FAILED(reason="shutdown")`.
- **`on_disconnect` clears `_ready`.** A dropped gateway no longer leaves `/imagine` racing the reconnect window — it returns 503 `DISCORD_NOT_READY` until `on_ready` fires again.
- **`_session_id_or_raise` guards interaction calls.** Reading `client.ws.session_id` during a reconnect window used to leak `AttributeError`; now it raises the structured `DiscordNotReadyError` (carries `code` and `remediation`), which the Flask layer maps to 503 with a JSON envelope.
- **Submit timeout is no longer terminal.** A Discord interaction POST that exceeds the 35-second budget transitions the job to `Status.SUBMITTED_UNCONFIRMED` and returns HTTP 202 + the job_id (with a `note` instructing the operator to poll `/wait` or `/status` rather than retry — MJ may have processed the original and a retry would double-bill). The job stays in `PENDING_GRID` so a late-arriving grid still matches it. New signal: `JOB_SUBMIT_TIMEOUT`.
- **`asyncio.get_running_loop()` throughout coroutines.** `on_message`, `on_message_edit`, `_post_interaction` use the running-loop accessor; `get_event_loop()` is deprecated in 3.10+ when no loop exists.

### Per-slot upscale failure isolation

- U1–U4 button presses now fire concurrently via `asyncio.gather(return_exceptions=True)`. A slow Discord on slot 1 no longer stalls 2–4. Per-slot failures emit `UPSCALE_PRESS_FAILED` (carries `slot`, `error_code`, `error_message`) and are recorded in `Job.upscale_press_failures`; surviving slots stay in `upscale_pending` and complete normally. Only when every requested slot's press fails does the job terminate — with `UPSCALE_ALL_BUTTONS_FAILED` for `upscale="all"` or `UPSCALE_BUTTON_FAILED` for single-slot. `JOB_FAILED.error_code` enum extended accordingly.

### Filename collision detection

- New helper `_safe_output_path` checks for an existing artifact at the intended `<asset_id>{suffix}{ext}` path before writing. On collision (two concurrent jobs sharing an asset_id), the request_token is woven into the filename — `<asset_id>_<token>{suffix}{ext}` — and `OUTPUT_PATH_COLLISION` is emitted with `intended_path`, `actual_path`, `kind` ('grid' or 'upscale'). The artifact lands either way; the operator learns from the signal that two jobs collided.

### Alpha keyer redesign

- `alpha_key_corners` defaults to `method="flood"` — 4-connected flood-fill from the four corners with per-channel tolerance. Subject regions surrounded by a darker outline stay opaque because the outline blocks the flood (the white penguin belly on a white background that the old global-threshold algorithm destroyed). A pure-Python BFS fallback handles the rare sentinel-color collision (`(255, 0, 255)` in the source image).
- `method="threshold"` preserves the original global-distance algorithm for callers in domains where flood-fill leaks (broken outlines, intentional gradients).
- The MCP `alpha_key` tool envelope now returns `method`, `tolerance`, `keyed_count`, `total_count`, and `keyed_ratio` (0.0–1.0). The agent can branch on the ratio: <0.1 means the keyer found no background; >0.9 means it ate the subject. Both warrant reject / reroll / swap method / skip alpha-keying.

### Vocabulary additions

- New tags: `DISCORD_DISCONNECTED`, `DISCORD_RECONNECTING`, `DISCORD_RECONNECT_FAILED`, `JOB_SUBMIT_TIMEOUT`, `OUTPUT_PATH_COLLISION`, `UPSCALE_PRESS_FAILED`. `JOB_FAILED.error_code` enum extended with `DISCORD_NOT_READY`, `UPSCALE_BUTTON_FAILED`, `UPSCALE_ALL_BUTTONS_FAILED`. 30 → 36 tags total; 40 → 51 emit callsites.

### Tools

- `tools/smoke_mcp_walk.py` — re-runnable live end-to-end check that drives every MCP tool over the real stdio JSON-RPC transport (not Python imports). Boots the bridge daemon, walks `bridge_health → compose_prompt → imagine → wait → crop_grid → [alpha_key?] → promote → log_append → read_prompt_log`. Alpha-key is opt-in via `--alpha-key`; default walk does crop → promote. Random `asset_id` per run for re-runnability. Exit codes: 0 pass, 1 walk failure, 2 environment misconfiguration. Bridge log dumped on failure for forensics.

### Renames since 0.1.0a1

- `cascade_img.instrumentation.runtime` → `cascade_img.vocabulary` (runtime module).
- `cascade_img/signals/versions/0.1.json` → `cascade_img/vocabulary/versions/0.1.json` (data path).
- `SignalVocabulary` → `Vocabulary`; `SignalEmitter` → `Emitter`.
- Project-root mirror moved from `signals/` to `vocabulary/`.

### Documentation

- README ToS notice rewritten as context (no prescriptions): Midjourney has no public API; driving it through a Discord user account is the established OSS pattern; both Discord's and Midjourney's Terms of Service prohibit user-account automation.
- `TOS.md` rewritten without behavioral prescriptions.
- `vocabulary/README.md` explains the catalog in plain language for first-time readers.

### Known limits (heading into 0.1.0)

- MJ-only backend; Flux, DALL-E, Imagen are v0.2+ work.
- Bridge tracks jobs in memory; restart drops in-flight state.
- `JOBS` is now LRU+TTL bounded (`MAX_JOBS`, `TERMINAL_AGE_SECONDS`) and emits `JOB_EVICTED`. Non-terminal jobs are never evicted, so an operator that submits faster than MJ completes can push the dict past `MAX_JOBS`; that's surfaced via `/health.total_jobs`.
- `/wait` is `threading.Condition`-based — no polling, no thread-per-request spin. Concurrent waits multiplex on `TERMINAL_CV`.
- `MidjourneyDiscordBackend` is synchronous (`requests`); the MCP server dispatches sync backend calls via `asyncio.to_thread` so concurrent MCP tool calls don't serialize.
- macOS and Linux only; Windows bridge is a v0.2 item.
- No webhook support; clients long-poll `/wait`.
- **TypeScript wrapper is a v0.2 deliverable.** The `@greenrosesystems/cascade-img` 0.0.1 placeholder on npm reserves the name. v0.1 is a Python-only ship; Node consumers either wait for the wrapper or call the bridge daemon's HTTP API directly.

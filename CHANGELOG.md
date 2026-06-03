# Changelog

All notable changes to cascade-img are recorded here. Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/); semantic versioning per [semver.org](https://semver.org/).

## [Unreleased]

### Package restructure (internal layout — public API unchanged)

- Reorganized `cascade_img` into concern-based packages so the tree is self-describing on a scan. `from cascade_img import …` is unchanged (the root re-exports everything); the three console scripts (`cascade-mj`, `cascade-mcp`, `cascade-mj-bridge`) are unchanged.
- New homes: `composer.py` / `log.py` → `prompt/`; the two front doors → `interfaces/` (`cli/` and `mcp/`); curation split by type → `curation/{geometry,color,sheets,select}/` with shared primitives in `curation/_shared.py`. The Midjourney backend stays under `backends/midjourney_discord/`.
- Renames for clarity: `cli/mj.py` → `interfaces/cli/generate_image.py`; `cli/registry.py` → `interfaces/cli/asset_registry.py`; `backends/midjourney_discord/backend.py` → `bridge_client.py`; `curation/crop_grid.py` → `curation/geometry/grid_crop.py`.
- The MCP server moved to `interfaces/mcp/` and split by concern: `tool_server.py` (FastMCP instance + entry point), `_envelope.py` (the response wrapper + shared backend/composer/log), and `tools/{prompt,generation,curation,log}_tools.py`. The 16 MCP tool names are unchanged.
- `pyproject` entry-point module paths updated to match; the wire string `backend="midjourney_discord"` is unchanged.

### Response-message actions (Wave F)

- **Drive every Midjourney response-message button without a human click.** `POST /action/<job_id>`, the `mj_action(job_id, action)` MCP tool, and `MidjourneyDiscordBackend.action` press the buttons on a completed job's upscaled (SOLO) image: `upscale_subtle`/`upscale_creative`, `vary_subtle`/`vary_strong`, `zoom_out_2x`/`zoom_out_1_5x`, `pan_left`/`right`/`up`/`down`, `animate_high`/`animate_low`, `favorite`. The bridge reads each button's **live** `custom_id` off the message (never reconstructs the uuid-bearing id); a missing button returns `BUTTON_NOT_FOUND`, a grid-only job `NO_UPSCALED_IMAGE`. New signals `MJ_ACTION_REQUESTED` / `MJ_ACTION_FAILED`.
- **Route the derived result back to the job.** A vary/zoom/pan/upscale/animation result is matched to its parent by Discord `message_reference == Job.upscale_message_id` (the only signal present on every family; recency is unsafe on a shared channel), downloaded to `<asset_id>_<kind>_<uuid8>`, and recorded in `Job.derived` with `MJ_DERIVED_RECEIVED` (or `MJ_DERIVED_FAILED`). `animate_*` is delivered as an animated WebP (`image/webp`), not mp4; `favorite` produces no artifact. The matchers are built from a verbatim live capture (`reviews/wave-f-receive-capture.md`), not guessed.
- **`load_dotenv` cwd fix.** Bare `load_dotenv()` walked to the installed package dir under the `cascade-mj-bridge` console-script entry point instead of the working directory, so a valid `.env` read as missing. Now `load_dotenv(find_dotenv(usecwd=True))` with a `CASCADE_DOTENV` explicit-path override for launchd/systemd/Docker hosts.
- **`mj_action` envelope.** `backend.action` unwraps the bridge's `{ok, result | error}` so the MCP tool returns single-level `{ok, result}` like every other tool (raising `BridgeActionError` with the stable code on failure) instead of a double-nested envelope.
- **Raw-capture hook.** `CASCADE_CAPTURE_RAW=<path>` makes the bridge append every watched MJ message verbatim (structure only) — observation instrumentation, OFF by default.
- **Clean single-signal shutdown.** The daemon now serves via an explicit `werkzeug.serving.make_server` on a worker thread and blocks the main thread on the shutdown event, calling `srv.shutdown()` on SIGINT/SIGTERM. `app.run()` did not reliably unblock on the signal handler's `SystemExit`, so the dev server could linger bound to the port and need a second signal (surfaced during live verification).
- New vocabulary tags: `MJ_ACTION_REQUESTED`, `MJ_ACTION_FAILED`, `MJ_DERIVED_RECEIVED`, `MJ_DERIVED_FAILED`; `mj_action` added to the MCP tool enum; `action` and `action_kind` enums constrained.

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

- `cascade_img.instrumentation.sdd` → `cascade_img.vocabulary` (runtime module).
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

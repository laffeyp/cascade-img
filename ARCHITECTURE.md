# Architecture

## Components

| Module | Role |
|---|---|
| `prompt/composer.py` | Turns composable prompt parts (subject, style reference, identity reference, aspect ratio, …) into a Midjourney prompt string (version-aware; supports V8.1 and V7). Pure; no I/O. |
| `prompt/prompt_log.py` | `PromptLog` — an append-only JSONL ledger that is the agent's working memory. |
| `backends/base.py` | `ImageGenerationBackend` — the pluggable interface (sync `imagine`/`wait`/`status`/`health`) — and `BackendCapabilities`. |
| `backends/midjourney_discord/bridge_client.py` | The v0.1 backend: a thin HTTP client that talks to the bridge daemon. |
| `backends/midjourney_discord/bridge.py` | The bridge daemon: a Flask HTTP server fronting a `discord.py-self` gateway connection to Midjourney. The only component that talks to Discord. |
| `backends/midjourney_discord/job_store.py` | A write-through SQLite sidecar to the bridge's in-memory job table, so a daemon restart can resume tracking in-flight jobs. |
| `curation/` | Post-generation image steps, grouped into `geometry/` (`grid_crop`, `auto_trim`), `color/` (`alpha_key`, `palette_quantize`), `sheets/` (`contact_sheet`, `sprite_sheet`), and `select/` (`score_grid`, `promote`). |
| `interfaces/mcp/tool_server.py` | A FastMCP server exposing the composer, backend, curation, and log as tools (`cascade-mcp`), with the response envelope in `_envelope.py` and the tools split across `tools/{prompt_tools,generation_tools,curation_tools,log_tools}.py`. |
| `interfaces/cli/generate_image.py` | The `cascade-mj` generate-and-record command. |
| `interfaces/cli/asset_registry.py` | Loads and validates the JSON asset registry (`asset_id` → prompt parts) that `cascade-mj` reads. |

## Data flow

cascade-img has two entry points — the `cascade-mj` CLI and the `cascade-mcp`
MCP server — and one long-running daemon, the bridge. Either entry point reaches
the bridge over local HTTP; the bridge is the only component that talks to Discord.
The bridge is long-lived because it owns the persistent Discord gateway connection
and the in-flight job table; the two entry points are stateless clients, started
and stopped per invocation.

```
   ┌───────────────────┐          ┌────────────────────────┐
   │  cascade-mj  (CLI) │          │ cascade-mcp (MCP server)│   entry points:
   │  human / script    │          │  agent host             │   one composes & generates,
   └─────────┬──────────┘          └───────────┬─────────────┘   one exposes tools
             └───────────────┬─────────────────┘
                             │   MidjourneyDiscordBackend — a thin HTTP client
                             │   POST /imagine · POST /video · GET /wait/<id>
                             │   GET /status/<id> · POST /action/<id> · GET /health
                             ▼
            ┌───────────────────────────────────────────┐
            │           cascade-mj-bridge                │   the daemon — the only
            │     Flask daemon · 127.0.0.1:5000          │   process that touches Discord
            └────────┬──────────────────────────▲────────┘
                     │ discord.py-self           │ grid · upscale · derived messages
                     ▼ (gateway + REST)          │
            ┌──────────────────┐         ┌──────────────────┐
            │     Discord      │ ◄─────► │    Midjourney    │
            └──────────────────┘         └──────────────────┘
```

A generation round: the caller composes a prompt and calls `imagine`; the
backend POSTs it to the bridge; the bridge fires the `/imagine` slash command
over Discord and tracks a job; Midjourney posts the grid (and, if requested,
upscales) back as Discord messages; the bridge matches those messages to the
job, downloads the images, and resolves the job. The caller long-polls
`/wait/<id>` until the job is terminal, then curates and logs.

**Two stores, often confused.** cascade-img keeps two separate persistent
records. The **prompt log** (`prompt/prompt_log.py`) is the *caller's* memory —
an append-only JSONL log of every attempt for an asset (prompt, outputs,
decision), read back to decide the next move. The **job store**
(`backends/midjourney_discord/job_store.py`) is the *daemon's* memory — a
write-through SQLite mirror of in-flight bridge jobs, so a restart resumes
tracking them instead of dropping them.

## HTTP API and the response envelope

The bridge exposes:

| Route | Purpose |
|---|---|
| `POST /imagine` | Submit a prompt; returns a `job_id`. |
| `POST /video` | Submit a native image→video prompt (must contain `--video`); returns a `job_id`. One unbound video at a time (`VIDEO_IN_FLIGHT` otherwise). |
| `GET /status/<job_id>` | Non-blocking job state read. |
| `GET /wait/<job_id>?timeout=<s>` | Long-poll until the job is terminal or the timeout fires. |
| `POST /action/<job_id>` | Press a response-message button on the job's upscaled result: on an image (vary / zoom / pan / re-upscale / animate / favorite), or on a video (`video_upscale`, `extend_high` / `extend_low`). |
| `GET /jobs` | All tracked jobs (diagnostics). |
| `GET /health` | Daemon up + Discord WebSocket connected. |

Every structured response follows one envelope:

```
{ "ok": true,  "result": { ... } }
{ "ok": false, "error": { "code": "STABLE_CODE", "message": "...", "remediation": "..." } }
```

The same shape is used by the MCP tools and the CLI, so an agent parses one
structure everywhere. `code` is a stable string an agent can branch on;
`remediation` is human-facing and points at `RUNBOOK.md`.

## Job lifecycle

```
QUEUED ──> SUBMITTED ──────────────> PROGRESS ──> UPSCALING ──> DONE
              │                          ^             │
              │ (interaction POST        │            └────────> DONE (no upscale)
              v  timed out)              │
        SUBMITTED_UNCONFIRMED ───────────┘

  any state ─────────────────────────────────────────────────> FAILED
```

- `SUBMITTED_UNCONFIRMED` means the Discord interaction POST timed out before
  returning. Midjourney may or may not have accepted the prompt, so the job
  stays claimable: if the grid arrives, the match path still resolves it; if
  not, `/wait` returns the bridge-side timeout. The job is never silently
  retried, which would risk billing the same render twice.
- `UPSCALING` is entered only when the caller requested upscales.

## Routing: per-job request token

Several jobs can be in flight with similar prompts. To route Midjourney's
echoed messages to the right job without prefix collisions, the bridge adds a
per-job token to each prompt as `--no cscidnocollide{token}`. The grid and
upscale matchers key on that token substring, not on the prompt text. A user
who supplies their own `--no` negatives must have them merged into the single
`--no` clause alongside the routing token (see the composer and `Job.tagged_prompt`).

### The grid-claim reservation

Discord delivers the grid as a message plus several edits, dispatched
concurrently on a thread pool. To prevent two threads from both downloading and
upscaling the same grid (a double-bill), the grid is claimed exactly once: a
thread reserves `grid_path` under the lock before any download, and a
concurrent edit that finds it already reserved returns early.

## Response-message actions

A finished upscale (a "SOLO" image) carries the buttons a human clicks in
Discord: re-upscale (subtle/creative), vary (subtle/strong), zoom-out, pan,
animate (image→video), favorite. `POST /action/<job_id>` drives them without a
click. The bridge records the SOLO message's id when an upscale lands
(`Job.upscale_message_id`), then on an action request it fetches that message,
reads the target button's **live** `custom_id` off the component, and presses
it via the same interaction primitive used for `U1`–`U4`. The uuid-bearing
`custom_id` is never reconstructed — a captured marker substring only *locates*
the button. A missing button returns `BUTTON_NOT_FOUND` rather than a wrong
press; a grid-only job returns `NO_UPSCALED_IMAGE`.

**Routing the result back.** Midjourney posts each derived result as a Discord
*reply* whose `message_reference` is the SOLO message id — the one marker
present on every family (vary/zoom/pan/upscale echo the routing token too;
animate and favorite do not). The bridge matches on that reference
(`_job_by_upscale_message_id`), distinguishes the final from MJ's progress
edits (a final carries a real result button, not a lone *Cancel Job*), downloads
it to `<asset_id>_<kind>_<uuid8>`, and appends an entry to `Job.derived`.
Recency is **not** used — the channel is
shared, and a foreign job's result interleaving the window would mis-route.
`animate_*` lands as an animated WebP (`image/webp`), not an mp4; `favorite`
produces no artifact and is a no-op. For `upscale="all"` the bridge keeps every per-slot SOLO message id
(`Job.upscale_message_ids`), so `mj_action(..., slot=N)` can target any of the
four images and a derived result replying to any of them routes home. Known v0.1
limit: a derived result that is itself a grid (vary/zoom/pan) is recorded in
`Job.derived` but not re-tracked as a new job, so its quadrants can't be acted on
in turn.

## Resilience

- The gateway runs in a reconnect loop with exponential backoff (capped). It
  terminates only on an authentication failure or an explicit shutdown.
- A dropped connection clears the ready flag; `/imagine` then returns `503`
  with `DISCORD_NOT_READY` until the gateway reconnects.
- Upscale button presses (`U1`–`U4`) run concurrently and are isolated: one
  slot failing does not sink the surviving slots.
- `/wait` multiplexes waiters on a single `threading.Condition` rather than
  spending a thread per request.
- The job table evicts terminal jobs by age and count (LRU + TTL) but never
  drops an in-flight job. (The SQLite job store rehydrates non-terminal jobs
  across a restart; pre-grid jobs fail `RESUBMIT_REQUIRED` because MJ
  processing is unconfirmable across the gap.)

## Adding a backend

1. Subclass `ImageGenerationBackend` (`backends/base.py`) and implement the
   synchronous `imagine`, `wait`, `status`, and `health`.
2. Declare a `BackendCapabilities` describing which prompt parts and aspect
   ratios it supports.
3. Return results in the same `{ok, result | error}` shape so the MCP server,
   CLI, and curation tools drive it unchanged.

The methods are synchronous: the MCP server dispatches them on a worker
thread (`asyncio.to_thread`), so wrapping blocking I/O in `async def` would
mark them as coroutines when they are not.

## Stable error codes

`error.code` values an agent can branch on:

| Code | Meaning |
|---|---|
| `DISCORD_400_OUTDATED` | The `/imagine` command version is stale; re-capture it. |
| `DISCORD_400_UNKNOWN_CHANNEL` | Channel/guild misconfigured (often a missing `MJ_GUILD_ID`). |
| `DISCORD_401` | Token rejected; re-capture it. |
| `DISCORD_NOT_READY` | The gateway was disconnected at submit time. |
| `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED` | Image fetch from Discord failed. |
| `MJ_UUID_MISSING` | Midjourney did not return the expected job identifiers. |
| `SUBMIT_FAILED` | The interaction POST itself failed. |
| `UPSCALE_BUTTON_FAILED` / `UPSCALE_ALL_BUTTONS_FAILED` | One or all upscale presses failed. |

See `RUNBOOK.md` for the operator-facing recovery procedure behind each code.

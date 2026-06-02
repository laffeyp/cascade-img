# Architecture

How cascade-img fits together, for a contributor adding a backend or anyone
tracing the data flow. The locked event vocabulary
(`packages/python/src/cascade_img/vocabulary/versions/0.1.json`) is the
ground truth for what the program reports at each step; this document explains
the shape around it.

## Components

| Module | Role |
|---|---|
| `composer.py` | Turns composable prompt parts (subject, style reference, identity reference, aspect ratio, …) into a Midjourney v7 prompt string. Pure; no I/O. |
| `vocabulary/` | The locked catalog of events the program may emit, plus the runtime (`emit`, `Vocabulary.validate`, `Emitter`). Every state transition names a tag here. |
| `backends/base.py` | `ImageGenerationBackend` — the pluggable interface (sync `imagine`/`wait`/`status`/`health`) — and `BackendCapabilities`. |
| `backends/midjourney_discord/backend.py` | The v0.1 backend: a thin HTTP client that talks to the bridge daemon. |
| `backends/midjourney_discord/bridge.py` | The bridge daemon: a Flask HTTP server fronting a `discord.py-self` gateway connection to Midjourney. The only component that talks to Discord. |
| `curation/` | `crop_quadrant`, `alpha_key_corners`, `promote` — post-generation image steps. |
| `log.py` | `PromptLog` — an append-only JSONL ledger that is the agent's working memory. |
| `mcp_server.py` | A FastMCP server exposing the composer, backend, curation, and log as tools (`cascade-mcp`). |
| `cli/mj.py` | The `cascade-mj` roll-and-record command. |

## Data flow

There are two front doors and one daemon. Both front doors speak to the bridge
over HTTP; the bridge is the only thing that touches Discord.

```
  cascade-mj (CLI)            cascade-mcp (MCP server)
        \                          /
         \                        /
          v                      v
        MidjourneyDiscordBackend  (HTTP client)
                    |
                    |  POST /imagine, GET /wait/<id>, /status/<id>, /jobs, /health
                    v
        cascade-mj-bridge  (Flask daemon, 127.0.0.1:5000)
            |                         ^
            | discord.py-self         | grid + upscale messages
            v  (gateway + REST)       |
        Discord  <----------------->  Midjourney
```

A generation round: the front door composes a prompt and calls `imagine`; the
backend POSTs it to the bridge; the bridge fires the `/imagine` slash command
over Discord and tracks a job; Midjourney posts the grid (and, if requested,
upscales) back as Discord messages; the bridge matches those messages to the
job, downloads the images, and resolves the job. The front door long-polls
`/wait/<id>` until the job is terminal, then curates and logs.

## HTTP API and the response envelope

The bridge exposes:

| Route | Purpose |
|---|---|
| `POST /imagine` | Submit a prompt; returns a `job_id`. |
| `GET /status/<job_id>` | Non-blocking job state read. |
| `GET /wait/<job_id>?timeout=<s>` | Long-poll until the job is terminal or the timeout fires. |
| `POST /action/<job_id>` | Press a response-message button (vary / zoom / pan / re-upscale / animate / favorite) on the job's upscaled image. |
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
echoed messages to the right job without prefix collisions, the bridge weaves a
per-job token into each prompt as `--no cscidnocollide{token}`. The grid and
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
press; a grid-only job returns `NO_UPSCALED_IMAGE`. The derived result (a new
grid, or a video for `animate_*`) lands back in the channel as a fresh MJ
message; v0.1 does not yet route it to a child job.

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
  drops an in-flight job. (In-memory at v0.1 — a restart drops in-flight state.)

## Vocabulary enforcement (Signal-Driven Development)

Every important state transition calls `emit("TAG", **payload)`. At emit time
the payload is validated against the locked catalog:

- unknown tag → raises;
- missing a required `payload` field → raises;
- a field not declared in `payload` or `optional_payload` → raises
  (the strict posture; relaxable via `CASCADE_STRICT_SIGNALS=false`).

`tools/check_vocabulary_parity.py` walks the source and fails if any `emit()`
callsite names a tag absent from the catalog. The catalog is mirrored
byte-for-byte at the repo root (`vocabulary/0.1.json`) for readers who don't
want to dig into the package; CI keeps the two identical. This is why tests
assert both a function's output and its emitted event sequence — the events are
part of the contract.

## Adding a backend

1. Subclass `ImageGenerationBackend` (`backends/base.py`) and implement the
   synchronous `imagine`, `wait`, `status`, and `health`.
2. Declare a `BackendCapabilities` describing which prompt parts and aspect
   ratios it supports.
3. Return results in the same `{ok, result | error}` shape so the MCP server,
   CLI, and curation kit drive it unchanged.

The methods are synchronous on purpose: the MCP server dispatches them on a
worker thread (`asyncio.to_thread`), so wrapping blocking I/O in `async def`
would only misrepresent the contract.

## Stable error codes

`error.code` values an agent can branch on (canonical set in the `JOB_FAILED`
entry of the vocabulary):

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

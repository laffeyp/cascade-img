# Runbook

How to run `cascade-img` end-to-end against a real Midjourney account, what breaks, and how to recover. Each failure mode named here has been exercised against live MJ.

> **Context.** Midjourney has no public API. Driving it through a Discord user account is the established OSS pattern for programmatic access. Both Discord's and Midjourney's Terms of Service prohibit user-account automation. See [TOS.md](./TOS.md).

---

## One-time setup

### Python 3.10 or newer

The daemon uses PEP 604 union syntax (`dict[str, X | None]`) which Python 3.9 cannot parse. macOS system Python is often 3.9; Homebrew gives you 3.11+.

```bash
which python3.11        # should resolve to /opt/homebrew/bin/python3.11
python3.11 --version    # >= 3.11.x
```

If missing: `brew install python@3.11`.

### Install the package

```bash
pip install cascade-img
# or, into a venv:
python3.11 -m venv .venv
source .venv/bin/activate
pip install cascade-img
```

This pulls in `discord.py-self`, `flask`, `requests`, `python-dotenv`, `Pillow`, and `mcp`. Three console scripts land on your `PATH`:

These three commands are console-script entry points declared in `pyproject.toml` under `[project.scripts]`. When the package is installed, pip generates a small executable wrapper for each one on your `PATH`, and each wrapper imports and calls the named function (for example, `cascade-mj` maps to `cascade_img.interfaces.cli.generate_image:main`). They are thin aliases to that code.

- `cascade-mj-bridge` — the MJ Discord bridge daemon
- `cascade-mcp` — the MCP server (Claude Desktop / Cursor / Cline)
- `cascade-mj` — the CLI that composes a prompt from a registry asset, fires the generation, waits, and logs the result

### Enable DevTools in the Discord desktop app

You'll need DevTools to capture `MJ_IMAGINE_VERSION`. Discord ships with DevTools disabled.

Edit `~/Library/Application Support/discord/settings.json` (macOS) and add inside the JSON object:

```json
"DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING": true,
```

The key name is `YOU_KNOW_WHAT_YOURE_DOING`, not `UNDERSTAND_THE_RISK`. There's a near-identical variant floating around that does nothing. The maintained variant is in `brunos3d/discord-enable-devtools`.

Cmd+Q Discord (a full quit, not window close), reopen, then **Cmd+Option+I** opens DevTools. Discord wipes this setting on every app update — re-add after auto-updates.

### Capture the five `.env` values

Drop a `.env` file in the working directory of `cascade-mj-bridge` (the daemon resolves it from its current working directory). If you run the daemon under a process manager (launchd, systemd, Docker) where the working directory isn't the `.env`'s directory, set `CASCADE_DOTENV=/abs/path/to/.env` to point at it explicitly.

Five values are required: the Discord token (one console snippet) plus four IDs you copy out of Discord.

#### `DISCORD_USER_TOKEN` — the credential

The only secret. Capture it from DevTools → **Console**. Enable mobile emulation first (**Cmd+Shift+M**, or the snippet returns `undefined`), then paste:

```javascript
const iframe = document.createElement('iframe');
console.log('Token: %c%s', 'font-size:16px;',
  JSON.parse(document.body.appendChild(iframe).contentWindow.localStorage.token));
iframe.remove();
```

The token is ~70 chars and starts with `MTU`, `MTk`, `OD`, or `Nz`. Treat it like a password — anyone holding it has full access to your account.

#### The four IDs

No snippet — each is a quick copy inside Discord:

| Variable | How to capture |
|---|---|
| `MJ_CHANNEL_ID` | Discord Settings → Advanced → Developer Mode ON. Right-click your MJ channel → Copy Channel ID. |
| `MJ_GUILD_ID` | Same trick — right-click the server icon → Copy Server ID. **Required when the MJ channel lives in a guild**; without it the Discord Interactions API treats the call as a DM and returns `400 Unknown Channel`. |
| `MJ_IMAGINE_VERSION` | Desktop Discord DevTools → Network. Fire `/imagine <any prompt>` in MJ channel. Find `POST /api/v9/interactions` → Payload → `data.version`. 19-digit number. Re-capture whenever MJ updates the slash command. |
| `MJ_IMAGINE_COMMAND_ID` | Same capture, `data.id`. The default `938956540159881230` is usually stable; only re-capture if you get 404s. |

Optional: `MJ_OUTPUT_DIR` (default `./generated`), `PORT` (default `5000`), `CASCADE_BRIDGE_URL` (default `http://127.0.0.1:5000`), `CASCADE_PROMPT_LOG` (default `./cascade-prompt-log.jsonl`), `CASCADE_DOTENV` (explicit `.env` path; overrides the cwd search), `CASCADE_JOB_DB` (persistent job store path; default `<MJ_OUTPUT_DIR>/cascade-jobs.db`).

### Pre-flight check

Before starting the daemon, run the pre-flight to surface any missing-config trap with a structured remediation:

```bash
cascade-mj-bridge --check-env --pretty
```

Returns `{"ok": true, "config": {...}}` on success or `{"ok": false, "error": {"code": "...", "message": "...", "remediation": "..."}}` on a missing/bad var. `MJ_GUILD_ID` is optional at the bridge's config layer; the failure mode if you skip it for a guild-bound channel surfaces at the first `/imagine` as `DISCORD_400_UNKNOWN_CHANNEL`.

For the full pre-flight ladder (env + Discord reachability + MCP server importable + discord.py-self importable):

```bash
cascade-mj-bridge --doctor --pretty
```

---

## Per-session bring-up

```bash
cascade-mj-bridge
```

Wait for **`Discord connected as <username>`** in the log. Until that line appears, `/imagine` calls return 503.

Verify:

```bash
curl -sS http://127.0.0.1:5000/health | python3 -m json.tool
```

Expected: `{"discord_ready": true, "pending_grid": 0, "upscaling": 0, "total_jobs": 0, "output_dir": "..."}`.

---

## Per-asset generation

### Via the CLI

Build a registry file once (JSON, keyed by `asset_id`):

```json
{
  "bird": {
    "subject": "pixel-art sprite of a small finch, side view",
    "constraints": ["transparent background"],
    "moodboard": "m7458053701014388751",
    "sref": "https://cdn.midjourney.com/.../0_0.png",
    "aspect_ratio": "1:1"
  }
}
```

Then:

```bash
cascade-mj bird --registry assets.json --pretty
cascade-mj bird --registry assets.json --upscale all --pretty
cascade-mj bird --registry assets.json --dry-run    # compose+log, no fire
```

JSON to stdout, human-readable progress to stderr. Exit 0 on `done`, 1 on `failed` or any structured error.

### Via the MCP server

In your agent host's MCP config (Claude Desktop, Cursor, Cline):

```json
{
  "mcpServers": {
    "cascade-img": {
      "command": "cascade-mcp"
    }
  }
}
```

The agent then sees the tool set — `compose_prompt`, `imagine`, `wait`, `status`, `bridge_health`, `crop_grid`, `alpha_key`, `promote`, `log_append`, `read_prompt_log` — and can drive the full loop autonomously.

### Via the Python library

```python
import asyncio
from cascade_img.prompt.composer import PromptComposer, Subject, StyleStack
from cascade_img.backends.midjourney_discord import MidjourneyDiscordBackend
from cascade_img.curation import crop_quadrant, alpha_key_corners, promote

backend = MidjourneyDiscordBackend()  # defaults to http://127.0.0.1:5000
prompt = PromptComposer().compose(
    Subject(text="a small finch"),
    style=StyleStack(moodboard="m7458...", sref="https://cdn..."),
    aspect_ratio="1:1",
)

async def go():
    j = await backend.imagine(prompt, asset_id="bird", upscale="1")
    r = await backend.wait(j["job_id"], timeout=360)
    return r

result = asyncio.run(go())
```

### Output paths

- Grid only: `<output_dir>/<asset_id>.{png,webp}`
- `--upscale 1..4`: `<output_dir>/<asset_id>.png` (the upscale) + `<asset_id>_grid.{png,webp}`
- `--upscale all`: `<output_dir>/<asset_id>_u1.png` ... `_u4.png` + `<asset_id>_grid.{png,webp}`

### Timeout calibration

`/wait` long-polls until the job hits `done` or `failed`. Calibrated per upscale mode:

| Upscale mode | timeout | rationale |
|---|---|---|
| `grid` (no upscale) | 180s | Grid alone: 30–90s typical |
| `1` / `2` / `3` / `4` | 360s | Grid + single upscale: 2–4 min |
| `all` | 600s | Grid + 4 upscales: 5–8 min on fast mode, sometimes more |

Exceeding the timeout doesn't kill the job — the bridge keeps tracking. Recover via:

```bash
curl -sS http://127.0.0.1:5000/jobs | python3 -m json.tool
curl -sS http://127.0.0.1:5000/status/<job_id> | python3 -m json.tool
```

---

## Failure modes

Every failure surfaces as a stable error code in the bridge's structured HTTP payload. LLM operators branch on `error_code`; humans read `remediation`.

### `MISSING_DISCORD_TOKEN` / `MISSING_CHANNEL_ID` / `MISSING_IMAGINE_VERSION`

Required env var not set. Run `cascade-mj-bridge --check-env` for the per-var report. Each carries a `remediation` pointing at the relevant capture step.

### `DISCORD_400_UNKNOWN_CHANNEL`

The MJ channel lives in a guild but `MJ_GUILD_ID` is not set. Discord's Interactions API treats the call as a DM and returns `400 Unknown Channel, code 10003`. Capture the guild ID (see the env table in the setup section) and restart the bridge.

### `DISCORD_400_OUTDATED`

Midjourney pushed a new slash-command version. Re-capture `MJ_IMAGINE_VERSION` from the Discord desktop DevTools and restart the bridge. This isn't a bug. It's the cost of depending on an unofficial slash command that Midjourney can change without notice.

### `DISCORD_401`

Token expired or rotated. Re-capture `DISCORD_USER_TOKEN`. Changing your Discord password invalidates all tokens.

### `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED`

Network blip during the PNG fetch from Discord CDN. Re-fire the asset.

### `MJ_UUID_MISSING`

Grid arrived but no U1-U4 buttons. Either MJ moderated the grid (check the channel manually) or the grid layout changed. If reproducible, capture the message components in DevTools and file an issue.

### Job sits at `submitted` forever

The bridge fired the Discord interaction but never received a matching MJ message in the channel. Likely causes:

- Midjourney moderated the prompt. Open the MJ channel in Discord; if MJ posted a moderation message instead of a grid, the prompt needs editing.
- The bridge lost track of the routing token. Each job tags its outbound prompt with `--no cscidnocollide<token>`, a token Midjourney echoes verbatim in its grid messages. If a Discord disconnect dropped the message that carried the echo, the bridge can't match it; check the bridge log for disconnects around the time the job was submitted.

### Two concurrent jobs not swapped

The bridge routes Midjourney's messages back to jobs using a per-job token appended to the outbound prompt as `--no cscidnocollide<token>` — not by prefix or substring match. Two jobs with identical leading prompts fired back-to-back are kept distinct because each carries its own token. If you do see two jobs receive each other's grids, file a bug with the bridge log; the routing is supposed to be collision-resistant.

### Midjourney V7 grid posted as a new message

Midjourney v7 sometimes posts the final grid as a separate new message rather than editing the original "(Waiting to start)" placeholder. The bridge's `_match_grid` has a second-pass fallback that matches in-progress jobs without a `grid_path` yet against any new message carrying the job's routing token, so the v7 new-message case still resolves.

### Bridge restarted mid-job

Bridge tracks jobs in memory. A restart vaporizes in-flight state. MJ-side generation continues server-side but the bridge can't surface results. Re-fire after restart.

### `DISCORD_NOT_READY` (HTTP 503)

The bridge's Discord WebSocket dropped and the reconnect loop is in flight. `/imagine` returns 503 with `{code: "DISCORD_NOT_READY", remediation: ...}` until the connection comes back. The reconnect loop has exponential backoff (2 → 60s cap). If the disconnect was transient, the next `/imagine` after the bridge reconnects succeeds. If the reconnect fails with `reason: "auth"`, the token was rejected — re-capture `DISCORD_USER_TOKEN` per setup §4.

### `SUBMITTED_UNCONFIRMED` (HTTP 202)

The Discord interaction POST didn't return within the bridge's 35-second budget, but MJ may still have processed the imagine. The job stays in `PENDING_GRID` with `status: "submitted_unconfirmed"` — a late-arriving grid still matches it normally. Poll `/wait` or `/status` rather than re-firing `/imagine` (a retry would double-bill if MJ processed the original).

### `UPSCALE_PRESS_FAILED` (per slot)

During `upscale="all"`, an individual U-button press (U1/U2/U3/U4) failed at the Discord interaction layer (network blip, slot-specific 5xx). Surviving slots stay in `upscale_pending` and complete normally; the failed slot is recorded on `Job.upscale_press_failures` with its `slot`, `error_code` (`HTTP_<status>` or the exception class), and `error_message`. The job stays in `UPSCALING`. If every requested slot's press fails, the job terminates with `UPSCALE_ALL_BUTTONS_FAILED` (or `UPSCALE_BUTTON_FAILED` for single-slot mode).

### `OUTPUT_PATH_COLLISION` (not a failure)

Two concurrent jobs shared an `asset_id`. The bridge detects the existing artifact and writes the second job's output to `<asset_id>_<request_token>{suffix}{ext}` instead of clobbering the first. Both artifacts land. Operator-side: investigate why two jobs got the same asset_id.

---

## Sprite-style language to fight photoreal drift

A style reference + moodboard alone isn't enough on small natural objects (feathers, scratch marks, keepsakes). Midjourney falls back to photorealism even with `--style raw`. Bake the aesthetic into every subject explicitly:

```
pixel-art sprite of <SUBJECT>, <COMPOSITION HINTS>, low-resolution 2D game sprite,
limited palette, handmade restrained sprite art, readable silhouette, centered,
transparent background
```

The redundant aesthetic phrases (pixel-art / low-resolution / limited palette / handmade / readable silhouette) are intentional. Midjourney weights repeated concepts higher, and a style reference alone needs reinforcement on small subjects. The `PromptComposer` folds `Subject.constraints` into the subject text so this idiom is one-liner.

If subject + sref + moodboard still drifts photoreal, raise the sref weight (`--sref <url>::2` or `::3`) and reduce `stylize` (e.g. `stylize=50`) to constrain Midjourney's prettifier.

---

## Identity-locked variants (V7 `--oref`)

When the goal is "same character, different pose/wings/expression", `--oref` is Midjourney v7's identity lock. It replaces v6's `--cref`, which is **not compatible with `--v 7`** (silently dropped if you pass it).

```python
IdentityStack(oref="https://cdn.discord.com/.../bird.png", ow=400)
```

- `ow` is omni-weight (0-1000). 100 = default (drifts), 400 = first useful tightness, 1000 = max. Bump higher when default drifts visibly.
- The reference URL must be a **single image, not a 2x2 grid**. A grid URL makes MJ average identity across 4 variants — "different birds flickering" drift. Use a single-image URL of the curated U-quadrant.

To get a single-image URL from a local file, upload to your MJ channel via the Discord API:

```bash
curl -X POST "https://discord.com/api/v9/channels/$MJ_CHANNEL_ID/messages" \
  -H "Authorization: $DISCORD_USER_TOKEN" \
  -F "files[0]=@assets/bird.png" \
  -F 'payload_json={"content":"canonical bird sprite (oref reference)"}'
```

Response has `attachments[0].url` — use that as `--oref`.

### When oref still drifts

1. Bump `ow=1000`.
2. Re-host the source image with cleaner alpha + tighter crop.
3. Use MJ's "Vary Region" inpaint (interactive Discord, not in the bridge yet).
4. Switch to a layered-sprite approach in your renderer — base body asset + separate overlay assets composited at runtime.

---

## Curation flow

After a roll completes, you have a grid (`<asset_id>.{png,webp}`) and optionally upscales. The curation kit handles cropping, optional alpha-keying, and promotion. The pipeline order is: **crop → (optional) alpha-key → promote**. The alpha-key step is opt-in per asset; the operator decides whether transparency is wanted.

```python
from cascade_img.curation import crop_quadrant, alpha_key_corners, promote

img = crop_quadrant("generated/bird.webp", quadrant=2)   # U2
# Optional — only when transparency is wanted:
img = alpha_key_corners(img, tolerance=24, method="flood")
img.save("staging/bird.png")
promote("staging/bird.png", "assets/bird.png")
```

Or as MCP tool calls:

```
crop_grid(src="generated/bird.webp", quadrant=2, dest="staging/bird.png")
# Optional:
alpha_key(src="staging/bird.png", dest="staging/bird_keyed.png", tolerance=24, method="flood")
promote(src="staging/bird_keyed.png", dest="assets/bird.png")
```

### Alpha-key method and tolerance

Two algorithms ship under `alpha_key_corners`:

- **`method="flood"` (default)** — 4-connected flood-fill from each corner. Subject regions surrounded by a darker outline stay opaque because the outline blocks the flood (the case where a white-bellied subject sits on a white background). Correct for most MJ sprite outputs.
- **`method="threshold"`** — global per-pixel distance from the corner-average color. Faster, simpler, but eats subject pixels whose color is close to the background. Available for domains where flood-fill leaks (broken outlines, intentional gradients from bg into subject).

`tolerance` (0-255 per channel) controls how permissive each algorithm is. Default 24 works for MJ's anti-aliased sprite art. The MCP `alpha_key` envelope returns `keyed_count`, `total_count`, and `keyed_ratio` (0.0-1.0). Typical sprite outputs key 0.4-0.8 of the frame. Ratios under 0.1 mean the keyer found no background (gradient, vignette, wrong tolerance, wrong method). Ratios over 0.9 mean the keyer ate the subject — reject and reroll, swap method, or skip alpha-keying for this asset.

Region backdrops (full-scene images) should not be alpha-keyed — the entire image is the asset.

---

## LLM-agent operation

The whole point of the package is that an LLM can close the loop without human-in-the-loop on every roll. The standard cycle:

1. **Compose** — `compose_prompt(subject, constraints, moodboard, sref, oref, ow, aspect_ratio)`.
2. **Fire** — `imagine(prompt, asset_id, upscale)` → returns `job_id`.
3. **Wait** — `wait(job_id, timeout=180|360|600)` → returns the full job record.
4. **Inspect** — read the PNG path with vision. Decide: promote / re-roll / escalate ow.
5. **Curate** — `crop_grid` → `alpha_key` → `promote` for the winner.
6. **Log** — `log_append(asset_id, prompt, job_id, outputs, agent_decision, agent_reason)`.

The next iteration starts with `read_prompt_log(n=5)` to surface what's already been tried for this asset. That's the working memory across loop iterations.

Failures carry a stable `error_code` and a `remediation` string. Codes the agent should branch on:

| code | recovery |
|---|---|
| `DISCORD_400_OUTDATED` | escalate to human — `MJ_IMAGINE_VERSION` needs re-capture |
| `DISCORD_400_UNKNOWN_CHANNEL` | escalate to human — channel lives in a guild but `MJ_GUILD_ID` is unset |
| `MISSING_DISCORD_TOKEN` / `MISSING_CHANNEL_ID` / `MISSING_IMAGINE_VERSION` / `INVALID_*` | escalate to human — one-time setup gap (raised by `Config.from_env` before the daemon starts) |
| `DISCORD_401` | escalate to human — token re-capture |
| `DISCORD_NOT_READY` (HTTP 503) | retry after a short delay; the bridge's reconnect loop is in flight |
| `MJ_UUID_MISSING` | re-roll once; if reproducible, escalate |
| `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED` | re-roll automatically |
| `UPSCALE_BUTTON_FAILED` / `UPSCALE_ALL_BUTTONS_FAILED` | retry the imagine; transient Discord interaction error |

A `/imagine` that returns HTTP 202 with `status: "submitted_unconfirmed"` is NOT a failure: poll `/wait` for the actual outcome. Re-firing `/imagine` for the same asset before `/wait` resolves would double-bill if MJ processed the original.

Everything else: re-roll up to N times, then escalate.

---

## Pre-release end-to-end check

`tools/smoke_mcp_walk.py` boots the bridge daemon and walks every MCP tool over the real stdio JSON-RPC transport (not Python imports) against live MJ. Useful as a release-gate before tagging:

```bash
python3 packages/python/tools/smoke_mcp_walk.py --env-file .env
python3 packages/python/tools/smoke_mcp_walk.py --env-file .env --upscale all --wait-timeout 240
python3 packages/python/tools/smoke_mcp_walk.py --env-file .env --alpha-key
```

Exit 0 means every tool returned `ok: true`, the promoted artifact landed, and the prompt log round-tripped. Exit 1 dumps the last 30 lines of the bridge log to stderr for forensics.

## Known limits (v0.1)

- Bridge tracks jobs in memory; restart drops in-flight state. `JOBS` is LRU+TTL bounded so memory doesn't grow unboundedly, but non-terminal jobs are never evicted — an operator submitting faster than MJ completes can push `total_jobs` past `MAX_JOBS`. Surfaced on `/health`.
- No automatic retry on moderation rejection.
- No webhook support; clients poll `/wait` (Condition-based wake on terminal — no polling, no thread-per-request spin).
- No `/blend` command support yet.
- Windows bridge is v0.2; macOS and Linux only at v0.1.
- Only the MJ backend; Flux / DALL-E / Imagen land v0.2+.
- Background removal is a corner-anchored heuristic (flood-fill or threshold). It handles the common "subject on uniform bg" case; complex matting (hair, fur, semi-transparency, multi-tone backgrounds) needs a learned model — slated as a v0.2 backend.

---

*Living document. Add new failure modes here as you hit them.*

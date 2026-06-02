# Operations

How to run `cascade-img` end-to-end against a real Midjourney account, what breaks, and how to recover. Generalized from the the default + 4.7 bring-up work that exercised every failure mode this doc covers.

> **ToS note.** This tool drives Midjourney through a Discord user account using `discord.py-self`. That violates both Discord's and Midjourney's Terms of Service. Accounts get banned. Use a sacrificial Discord account. See [TOS.md](./TOS.md).

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

- `cascade-mj-bridge` — the MJ Discord bridge daemon
- `cascade-mcp` — the MCP server (Claude Desktop / Cursor / Cline)
- `cascade-mj` — the unified roll-and-log CLI

### Enable DevTools in the Discord desktop app

You'll need DevTools to capture `MJ_IMAGINE_VERSION`. Discord ships with DevTools disabled.

Edit `~/Library/Application Support/discord/settings.json` (macOS) and add inside the JSON object:

```json
"DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING": true,
```

The key name is `YOU_KNOW_WHAT_YOURE_DOING`, not `UNDERSTAND_THE_RISK`. There's a near-identical variant floating around that does nothing. The maintained variant is in `brunos3d/discord-enable-devtools`.

Cmd+Q Discord (a full quit, not window close), reopen, then **Cmd+Option+I** opens DevTools. Discord wipes this setting on every app update — re-add after auto-updates.

### Capture the five `.env` values

Drop a `.env` file in the working directory of `cascade-mj-bridge`. Required:

| Variable | How to capture |
|---|---|
| `DISCORD_USER_TOKEN` | DevTools → Console → run the iframe localStorage snippet below. 70 chars, starts with `MTU`, `MTk`, `OD`, or `Nz`. Treat as password. |
| `MJ_CHANNEL_ID` | Discord Settings → Advanced → Developer Mode ON. Right-click your MJ channel → Copy Channel ID. |
| `MJ_GUILD_ID` | Same trick — right-click the server icon → Copy Server ID. **Required when the MJ channel lives in a guild** (see Failure mode #2). |
| `MJ_IMAGINE_VERSION` | Desktop Discord DevTools → Network. Fire `/imagine <any prompt>` in MJ channel. Find `POST /api/v9/interactions` → Payload → `data.version`. 19-digit number. Re-capture whenever MJ updates the slash command. |
| `MJ_IMAGINE_COMMAND_ID` | Same capture, `data.id`. The default `938956540159881230` is usually stable; only re-capture if you get 404s. |

Optional: `MJ_OUTPUT_DIR` (default `./generated`), `PORT` (default `5000`), `CASCADE_BRIDGE_URL` (default `http://127.0.0.1:5000`), `CASCADE_PROMPT_LOG` (default `./cascade-prompt-log.jsonl`).

**Token capture snippet** (paste in Console, Cmd+Shift+M to enable mobile emulation first or this returns undefined):

```javascript
const iframe = document.createElement('iframe');
console.log('Token: %c%s', 'font-size:16px;',
  JSON.parse(document.body.appendChild(iframe).contentWindow.localStorage.token));
iframe.remove();
```

### Pre-flight check

Before starting the daemon, run the pre-flight to surface any missing-config trap with a structured remediation:

```bash
cascade-mj-bridge --check-env --pretty
```

Returns `{"ok": true, "config": {...}}` on success or `{"ok": false, "error": {"code": "...", "message": "...", "remediation": "..."}}` on a missing/bad var. The `MJ_GUILD_ID` trap surfaces here as `MISSING_GUILD_ID` rather than as an unrecoverable Discord 400 at first `/imagine`.

For the full pre-flight ladder (env + Discord reachability + MCP server importable + discord.py-self importable):

```bash
cascade-mj-bridge --doctor --pretty
```

---

## Per-session bring-up

```bash
cascade-mj-bridge
```

Wait for **`Discord connected as <username>`** in the log. Until that line appears, `/imagine` calls return 503. The bridge emits `DISCORD_CONNECTED` (signal) at the same moment.

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

The agent then sees ten tools — `compose_prompt`, `imagine`, `wait`, `status`, `bridge_health`, `crop_grid`, `alpha_key`, `promote`, `log_append`, `read_prompt_log` — and can drive the full loop autonomously.

### Via the Python library

```python
import asyncio
from cascade_img.composer import PromptComposer, Subject, StyleStack
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

Every failure surfaces as a stable error code through both the bridge's structured payload (HTTP) and the daemon's `JOB_FAILED` signal (emitted via `cascade_img.instrumentation.runtime`). LLM operators branch on `error_code`; humans read `remediation`.

### `MISSING_DISCORD_TOKEN` / `MISSING_CHANNEL_ID` / `MISSING_IMAGINE_VERSION`

Required env var not set. Run `cascade-mj-bridge --check-env` for the per-var report. Each carries a `remediation` pointing at the relevant capture step.

### `MISSING_GUILD_ID` → would be `DISCORD_400_UNKNOWN_CHANNEL`

the default trap. When the MJ channel lives in a guild, `MJ_GUILD_ID` must be set. Without it, Discord treats the interaction as a DM and returns `400 Unknown Channel, code 10003`. The pre-flight surfaces this before the daemon starts; if you get the Discord 400 at runtime, capture the guild ID per setup §4 and restart.

### `DISCORD_400_OUTDATED`

MJ pushed a new slash command version. Re-capture `MJ_IMAGINE_VERSION` from desktop DevTools (setup §4) and restart the bridge. This isn't a bug — it's the cost of riding the slash-command API.

### `DISCORD_401`

Token expired or rotated. Re-capture `DISCORD_USER_TOKEN`. Changing your Discord password invalidates all tokens.

### `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED`

Network blip during the PNG fetch from Discord CDN. Re-fire the asset.

### `MJ_UUID_MISSING`

Grid arrived but no U1-U4 buttons. Either MJ moderated the grid (check the channel manually) or the grid layout changed. If reproducible, capture the message components in DevTools and file an issue.

### Job sits at `submitted` forever

The MJ message never matched the bridge's prompt-substring expectation. Either:
- MJ moderated the prompt — check the channel manually for a different MJ response.
- Your prompt leads with characters that broke the substring matcher. Reword the leading 2–3 words to be more conventional.

### Two jobs swapped

Bridge matches FIFO. Two identical leading prompts fired back-to-back can swap. Include a unique disambiguator in the leading subject (the bridge looks at the prompt's prefix only).

### MJ V7 grid never matched

The the default patch addresses this — MJ V7 posts the final grid as a separate new message rather than editing the original. The bridge's `_match_grid` has a fallback path that catches in-progress jobs without a grid_path yet. The path that fired is surfaced in the `GRID_MATCHED` signal as `match_path = "progress_fallback"`.

### Bridge restarted mid-job

Bridge tracks jobs in memory. A restart vaporizes in-flight state. MJ-side generation continues server-side but the bridge can't surface results. Re-fire after restart.

### MJ ban email

Sacrificial account per design. Get a fresh account, capture new credentials, restart.

---

## Sprite-style language to fight photoreal drift

Sref + moodboard alone isn't enough on small natural objects (feathers, scratch marks, keepsakes). MJ falls back to photorealism even with `--style raw`. Bake the aesthetic into every subject explicitly. The the default pattern:

```
pixel-art sprite of <SUBJECT>, <COMPOSITION HINTS>, low-resolution 2D game sprite,
limited palette, handmade restrained sprite art, readable silhouette, centered,
transparent background
```

The redundant aesthetic phrases (pixel-art / low-resolution / limited palette / handmade / readable silhouette) are intentional — MJ weights repeated concepts higher, and the sref alone needs reinforcement on small subjects. The `PromptComposer` folds `Subject.constraints` into the subject text exactly so this idiom is one-liner.

If subject + sref + moodboard still drifts photoreal, bump sref weight (`--sref <url>::2` or `::3`) and/or reduce stylize (`stylize=50`) to constrain MJ's prettifier.

---

## Identity-locked variants (V7 `--oref`)

When the goal is "same character, different pose/wings/expression", `--oref` is V7's identity lock. Replaces V6's `--cref` (which is **not compatible with `--v 7`** — silently dropped).

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

After a roll completes, you have a grid (`<asset_id>.{png,webp}`) and optionally upscales. The curation kit handles cropping, alpha-keying, and promotion:

```python
from cascade_img.curation import crop_quadrant, alpha_key_corners, promote

img = crop_quadrant("generated/bird.webp", quadrant=2)   # U2
img = alpha_key_corners(img, tolerance=40)               # for character/item sprites
img.save("staging/bird.png")
promote("staging/bird.png", "assets/bird.png")
```

Or as MCP tool calls:

```
crop_grid(src="generated/bird.webp", quadrant=2, dest="staging/bird.png")
alpha_key(src="staging/bird.png", dest="staging/bird_keyed.png", tolerance=40)
promote(src="staging/bird_keyed.png", dest="assets/bird.png")
```

### Alpha-key tolerance

The default 40 (0-255 per channel) is the the default calibration for MJ's soft anti-aliased sprite art. Too tight (10-20) leaves a halo; too loose (60+) eats into the sprite. The `ALPHA_KEY_APPLIED` event reports the four-corner average and the keyed-pixel ratio — a typical sprite keys 30-70% of pixels. Outside that band suggests tolerance is wrong.

Region backdrops (full-scene images) should NOT be alpha-keyed — the entire image is the asset.

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

Failures carry a stable `error_code` and a `remediation` string. Five codes the agent should branch on:

| code | recovery |
|---|---|
| `DISCORD_400_OUTDATED` | escalate to human — `MJ_IMAGINE_VERSION` needs re-capture |
| `MISSING_GUILD_ID` / `MISSING_*` | escalate to human — one-time setup gap |
| `DISCORD_401` | escalate to human — token re-capture |
| `MJ_UUID_MISSING` | re-roll once; if reproducible, escalate |
| `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED` | re-roll automatically |

Everything else: re-roll up to N times, then escalate.

---

## Known limits (v0.1)

- Bridge tracks jobs in memory; restart drops in-flight state.
- No automatic retry on moderation rejection.
- No webhook support; clients poll `/wait`.
- No `/blend` command support yet.
- Windows bridge is v0.2; macOS and Linux only at v0.1.
- Only the MJ backend; Flux / DALL-E / Imagen land v0.2+.

---

*Living document. Append surfaced operational lessons as new failure modes are discovered.*

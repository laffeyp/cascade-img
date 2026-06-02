# Cascade Asset Pipeline

A local HTTP bridge that lets Claude (or any client) generate Midjourney assets
on demand and have them land on disk under predictable filenames, ready to be
curated into `/Assets/Art/` in Unity.

Flow: client `POST /imagine` → bridge fires `/imagine` to MJ over the Discord
interactions API as your user → bridge watches the MJ channel via a self-bot WS
connection → grid PNG (and optionally U1–U4 upscales) saved to `./generated/`.

Heads up: this drives Midjourney via your Discord user token rather than an
official API. Both Discord and Midjourney prohibit automation in their ToS, and
accounts get banned. We're going ahead anyway — just don't pretend it's
sanctioned, and keep a sacrificial account if that matters to you.

## Files

```
asset_pipeline/
├── mj_bridge.py     # Flask + discord.py-self bridge (runs as a long-lived daemon)
├── mj_client.py     # tiny CLI + import-able helper
├── .env.example     # config template
├── generated/       # output PNGs land here
└── README.md
```

## Install

```bash
pip install -U "discord.py-self" flask requests python-dotenv
```

Python 3.10+.

## Configure

Copy the template and fill in four values:

```bash
cp .env.example .env
```

| Variable | How to get it |
|---|---|
| `DISCORD_USER_TOKEN` | discord.com web client → DevTools → Network → click any request → copy the `Authorization` request header value. Treat like a password. |
| `MJ_CHANNEL_ID` | Right-click your private MJ channel → Copy Channel ID. (Enable Developer Mode in Settings → Advanced first.) |
| `MJ_IMAGINE_VERSION` | DevTools → Network → run `/imagine` once manually → find the `POST /api/v9/interactions` → request body → copy `data.version`. |
| `MJ_IMAGINE_COMMAND_ID` | Same capture, copy `data.id`. Default in `.env.example` is usually current. |

The `MJ_IMAGINE_VERSION` value is the one that goes stale. Midjourney bumps it
whenever they update the slash command (every few weeks). When the bridge
suddenly starts returning `discord 400: This command is outdated` errors,
re-capture this value and restart.

## Run

```bash
python mj_bridge.py
```

The bridge logs to stdout. Wait until you see `Discord connected as <you>` —
that means the WebSocket session is up and `/imagine` calls will succeed.

Hit `GET http://127.0.0.1:5000/health` to confirm.

## HTTP API

### `POST /imagine`

Submit a generation. Returns immediately with a `job_id`.

```json
{
  "prompt": "a glowing turquoise glass chip, jewel-tone, deep gem facets, centered, transparent background, neo-retro treasure UI icon --ar 1:1 --v 7 --style raw",
  "asset_id": "relic_chip_v01",
  "upscale": 1
}
```

- `prompt` (required) — full MJ prompt, all flags included.
- `asset_id` (optional) — filename stem. Sanitized to `[A-Za-z0-9._-]`, truncated to 80 chars. If omitted, gets a random one.
- `upscale` (optional) — `null` (grid only), `1`–`4` (single upscale, lands at `<asset_id>.png`), or `"all"` (four files `<asset_id>_u1.png` ... `_u4.png`).

Response: `{job_id, asset_id, status, upscale}`.

### `GET /status/<job_id>`

Cheap poll. Returns the full job record:

```json
{
  "job_id": "…",
  "asset_id": "relic_chip_v01",
  "status": "upscaling",
  "progress": "upscaling",
  "image_path": "/Users/.../generated/relic_chip_v01.png",
  "grid_path":  "/Users/.../generated/relic_chip_v01_grid.png",
  "upscale_paths": {"1": "..."},
  "upscale_pending": [],
  "error": null
}
```

`status` progresses: `queued → submitted → progress → (upscaling) → done`, or any
of those → `failed` with `error` set.

### `GET /wait/<job_id>?timeout=120`

Long-poll. Blocks up to `timeout` seconds (default 120), returns the job once
`status` is `done` or `failed`. Returns 504 with `timed_out: true` if not.

### `GET /jobs`

All jobs since the bridge started. Useful for debugging.

### `GET /health`

`{discord_ready, pending_grid, upscaling, total_jobs, output_dir}`.

## CLI

```bash
python mj_client.py \
  --asset relic_chip_v01 \
  --upscale 1 \
  "a glowing turquoise glass chip, jewel-tone, deep gem facets, centered, transparent background, neo-retro treasure UI icon --ar 1:1 --v 7 --style raw"
```

Streams progress to stderr, prints final job JSON to stdout, exits 0 on `done`.

## Output naming

```
upscale=None    →  <asset_id>.png                              (grid)
upscale=1..4    →  <asset_id>.png        (the upscaled image)
                   <asset_id>_grid.png   (the 2×2 grid, kept for reference)
upscale="all"   →  <asset_id>_u1.png ... <asset_id>_u4.png
                   <asset_id>_grid.png
```

For most production sprites you want `upscale: 1` (or whichever U-slot looked
best in a manual review). For exploration / picking between four variants, use
`"all"`.

---

## Runbook: operational prompt for local Claude

Paste this into your local Claude session (Claude Code or whatever agent loop
you're driving) when you want it to generate Cascade assets autonomously:

> You have a local Midjourney bridge at `http://127.0.0.1:5000`. To generate an
> asset:
>
> 1. **Compose the prompt.** Read `Cascade/cascade_spec_v_0_6_build_team.md`
>    § 10 (Visual design direction) and § Appendix A (Tier table). Use the
>    Cascade style stack — see "Style consistency" below in the README. Every
>    prompt must include `--sref <code>` and `--profile <code>` matching the
>    Cascade style profile, plus the right `--ar` for the asset type.
>    **For tier N > 1, derive from tier N-1**: image-prompt with the locked
>    lower-tier asset URLs at the start of the prompt + tier-up language. See
>    "Tier derivation" in the README for the workflow.
>
> 2. **Pick an `asset_id`** that matches the Unity sprite naming convention in
>    the spec — e.g. `relic_chip_v01`, `relic_bead_v01`, `board_frame_main`,
>    `particle_burst_shimmer_v01`. Always version-suffix (`_v01`, `_v02`) so
>    re-runs don't clobber.
>
> 3. **`POST /imagine`** with `{prompt, asset_id, upscale: 1}` (use `"all"` only
>    when exploring). Capture the `job_id`.
>
> 4. **`GET /wait/<job_id>?timeout=180`** — blocks until `done` or `failed`.
>    Read `image_path` from the response; the file is on disk in
>    `Cascade/asset_pipeline/generated/`.
>
> 5. **On `failed`**: read `error`. If it's a MJ moderation rejection,
>    re-prompt with less ambiguous language. If it's `discord 400 ... outdated`,
>    the user needs to re-capture `MJ_IMAGINE_VERSION` — stop and ask.
>
> 6. **Curate, don't auto-commit.** Generated assets land in
>    `generated/`, not in `/Assets/Art/`. After visual review, the human moves
>    chosen images into the Unity project. Don't move files yourself.

---

## Style consistency for Cascade

Cascade's spec asks for a single coherent visual identity across 8 relic tiers
(Chip → Mythic Core), a board frame, particles, and UI icons. If each prompt is
free-form, you get 8 different art styles and no atlas. Midjourney has three
composable systems that solve this — use them as a stack.

### The three layers

**Style Reference (`--sref <code>`)** — color palette, brush, surface texture.
You can pass an integer code that MJ has internally indexed (millions exist —
explore via `--sref random`, lock the one you like) or a public URL to a
reference image. Sref codes can be combined and weighted:
`--sref 1344854894::5 3505500910::2`.

**Personalization Profiles / Moodboards (`--profile <code>`)** — broader
aesthetic preferences derived from images you upload. Build a moodboard inside
the MJ web UI with 20–40 reference images (Neopets sprite work, Pogo game art,
classic stained-glass icons, jewel macro photography — whatever maps to the
"neo-retro treasure UI" pillar in § 3.7). MJ generates a profile code. Pass it
with `--profile abc123 def456` (multiple allowed). Moodboards and personalization
profiles share this same `--profile` parameter.

**Character / Object Reference (`--cref <url>` / `--oref <url>`)** — identity
lock. Less useful for an abstract gem icon than for "the same character across
8 poses", but `--oref` (object reference, V8) is worth experimenting with for
keeping a tier's silhouette consistent across re-rolls. `--cw 0–100` controls
how strict the reference match is.

### Recommended Cascade workflow

Set this up once, then every per-tier prompt becomes a thin variation.

1. **Build the Cascade moodboard.** In MJ web UI → Moodboards → new board.
   Upload references that span the four things you actually want: (a) jewel
   tones / glass / facets, (b) framed icon composition with strong silhouette,
   (c) the "small collectible object" feel from late-90s/early-2000s Pogo,
   Neopets, Yahoo Games, (d) the 2026 rendering polish. Save the moodboard
   code.
2. **Roll a style ref.** Run `the symbol of a treasure --sref random --ar 1:1
   --v 7` a dozen times. When one nails the color/material feel, lock that
   sref code.
3. **Codify the style stack.** Pick the canonical Cascade stack:
   `--profile <moodboard_code> <personalization_code> --sref <code> --style raw`.
   Use `--style raw` to suppress MJ's default opinion-injection so your sref
   actually drives.
4. **Per-tier prompts vary only the subject.** Template:
   `<tier subject description, 1 sentence, ending with "centered, transparent
   background"> --ar 1:1 --v 7 --style raw --profile <…> --sref <…>`.
   For Cascade's 8 tiers, the subject descriptions live in
   spec § Appendix A — Chip, Bead, Rune, Sigil, Relic, Idol, Crown, Mythic
   Core. Increase rarity language and material complexity as tier rises (Chip
   → "small glass chip"; Mythic Core → "crystalline core wrapped in living
   filigree").
5. **For non-piece assets** (board frame, particles, UI icons): change `--ar`
   (`9:16` for board, `1:1` for particles, etc.) but keep the same
   `--profile` / `--sref`. Different subject, same world.

### What I'd flag as worth testing next

The story I keep finding is that **moodboards drive identity, sref drives
material, personalization drives taste, and they compose**. The right call is
probably: spend a session in MJ web UI building one tight moodboard for
Cascade, lock one sref, then drive everything through this pipeline with that
fixed stack. Doing the moodboard work outside the pipeline once is much faster
than trying to encode the look across many prompts.

If you want this baked into the bridge (e.g., a `style_profile: "cascade"`
config that auto-appends `--profile X --sref Y --style raw` to every prompt),
say the word — that's a small change.

---

## Tier derivation: using merges to make merge art

Cascade's core loop is "two same-tier pieces merge into one next-tier piece."
The asset pipeline mirrors this directly — instead of prompting all 8 tiers
cold and hoping they read as a coherent progression, derive each tier visually
from the previous one using Midjourney's image composition. The whole atlas
inherits a continuous visual genome, exactly mirroring the game's merge logic.
This is also how you avoid the "8 disconnected art styles" failure mode that
hits anyone who tries to prompt all 8 tiers independently.

Three ways MJ supports this. One works in the current bridge with zero changes.

**Image prompting via URLs (works now).** `/imagine` accepts image URLs at the
start of the prompt text. Put one or two URLs of the lower-tier asset, then the
text prompt describing the merged result:

```
https://cdn.discordapp.com/.../relic_chip_v01.png \
https://cdn.discordapp.com/.../relic_chip_v01.png \
two glass chips fused into one larger crystalline bead, jewel-tone,
inherited turquoise + emerald palette intensified, more elaborate metallic
filigree edge, single collectible game item centered on dark midnight-velvet
background, late-90s Pogo treasure-UI icon with 2026 polish
--ar 1:1 --v 7 --style raw --p m7451565286148276262 --iw 1.5
```

Use the Discord CDN URL for assets already in your MJ channel (right-click any
MJ-generated image → Copy Link), or host on imgur. The `--iw <n>` flag (image
weight, 0.5–2) controls how strongly the source images influence the result vs
the text prompt — higher = more visual inheritance from the merged pieces.

**`/blend` (separate slash command, not in the bridge yet).** Takes 2–5 image
attachments, no text prompt, returns a pure composition. Cleaner for the case
of "just visually merge these two, you decide the result." Adding it: new
endpoint accepting image URLs, upload them to Discord first, fire a different
slash-command interaction. ~80 lines. Worth doing if image-prompting via
`/imagine` proves too noisy.

**`--oref <url1> <url2>` (V8 object reference).** Multi-image identity lock.
Strongest form of "this new piece *is* those two pieces combined" — MJ
extracts object identity rather than general style. V8 only; not useful until
V8 leaves alpha.

**Recommended workflow.** Generate Tier 1 (Chip) cleanly using the moodboard
prompt. Lock the best Chip. For Tier 2 (Bead), use image-prompting on two
copies of that locked Chip with tier-up language ("two chips fused into one
larger bead, inherited palette intensified, more elaborate edge"). Lock the
best Bead. Repeat up the ladder. By Tier 8 (Mythic Core) the asset carries
visual DNA from every tier below it, which is exactly what the merge mechanic
implies the world should look like.

---

## Troubleshooting

**`discord 400: This command is outdated, please try again in a few minutes`**
MJ updated the imagine command. Re-capture `MJ_IMAGINE_VERSION` from
devtools, update `.env`, restart the bridge. This isn't a bug, it's the cost
of riding the slash-command API.

**`discord 401`**
Token expired or wrong. Re-capture `DISCORD_USER_TOKEN`. If you recently
changed your Discord password, all tokens were invalidated.

**`could not find MJ job uuid in grid components`**
The bridge expected upsample buttons (U1–U4) on the grid message and didn't
find them. This can happen on V8 where MJ may attach a different button
layout, or on moderation-flagged grids. Check the message manually in Discord.

**Job sits at `submitted` forever**
The MJ message never matched your prompt's leading text. Either MJ moderated
the prompt (you'd see a different MJ message — check the channel manually),
or your prompt starts with something exotic enough that the substring match
failed. Try a less elaborate leading phrase.

**Two jobs with identical leading prompts get swapped**
Matching is FIFO. If you fire two identical prompts back-to-back, the first
MJ message goes to the first job. Avoid this by including a unique tag at
the start of each prompt (the leading text MJ echoes back) or just space
calls out by a few seconds.

**You got the dreaded MJ ban email**
That was the deal we made. Get a fresh account, plug new credentials into
`.env`, keep going. If this happens repeatedly, switch to a tier the
moderation system likes less (it tends to come down harder on volume + niche
content combinations).

## Known limits

- The bridge tracks jobs in memory. Restart it and in-flight jobs vanish — re-submit.
- No automatic retry on moderation rejection. Bridge marks the job failed; up to you to re-prompt.
- No rate limiting on the bridge side. MJ's own per-account fast-mode cap (3 concurrent jobs on most plans) is the actual throttle.
- No webhook support. Clients poll `/wait/<job_id>` instead.
- No `/imagine`-with-image-attachments (uploading files alongside the prompt). Text + sref URLs + image-prompt URLs inline in the prompt text all work.
- No `/blend` command support (the multi-image-attachment "just combine these" mode). For now, use image-prompt URLs in `/imagine` — see "Tier derivation" above.

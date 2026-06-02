# Cascade Asset Pipeline — Operational Runbook

*Written 2026-05-26 during the live Sprint 4.0 bring-up. Captures the actual technical process we walked: what worked, what broke, what we patched, in the order we hit it. The Cascade README documents the bridge's API surface; this doc is the Katybird-specific application — the friction points, the surprise dependencies, the calibration constants we landed on.*

*If you're reading this fresh, start at "One-time setup" and follow top-down. If you're resuming after a session, start at "Per-session bring-up".*

---

## Architecture in one paragraph

`tools/cascade-asset.ts` (this repo) drives `Cascade/asset_pipeline/mj_bridge.py` (sibling project) over `http://127.0.0.1:5000`. The bridge is a Flask + discord.py-self daemon that fires `/imagine` slash commands as your Discord user via the Discord interactions API, watches the MJ channel via WebSocket, and saves resulting PNGs to `Cascade/asset_pipeline/generated/`. The bird → MJ → bridge → disk loop is asynchronous: the bridge tracks jobs in memory and emits `done`/`failed` status; your client polls `/status` or long-polls `/wait`. The Katybird piece (`tools/cascade-asset.ts`) bakes in the prompt template — moodboard profile + character/environment srefs + the sprite-art subject language — and writes per-roll entries to `handoff/cascade-prompts/sprint-4.0.md` for reproducibility.

---

## One-time setup

### 1. Python 3.10+ (NOT 3.9)

The bridge uses PEP 604 union syntax (`dict[str, asyncio.AbstractEventLoop | None]`) which Python 3.9 cannot parse. On macOS the system `python3` is often 3.9; Homebrew gives you 3.11 or newer.

```bash
which python3.11        # should resolve to /opt/homebrew/bin/python3.11
python3.11 --version    # >= 3.11.x
```

If missing: `brew install python@3.11`.

### 2. Install bridge deps for the right Python

If `pip3 install` goes to a different Python (e.g. 3.9), the bridge will fail at import. Install explicitly against 3.11:

```bash
/opt/homebrew/bin/python3.11 -m pip install -U "discord.py-self" flask requests python-dotenv
```

The `discord.py-self` package is the self-bot client. The other three are the Flask side. PyNaCl is *not* installed (the bridge logs a voice-unsupported warning but doesn't need it).

### 3. Enable DevTools in the Discord desktop app

Required to capture `MJ_IMAGINE_VERSION`. The web client doesn't expose `/imagine` reliably; the desktop app does, but Discord ships with DevTools disabled.

Edit `~/Library/Application Support/discord/settings.json`. Add inside the JSON object:

```json
"DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING": true,
```

Note: **the key name is `YOU_KNOW_WHAT_YOURE_DOING`**, not `UNDERSTAND_THE_RISK`. There's a near-identical variant floating around the internet that does nothing. The maintained variant is in `brunos3d/discord-enable-devtools`.

Cmd+Q Discord (a full quit, not window close), reopen, then **Cmd+Option+I** opens DevTools. Discord wipes this setting on every app update — you'll need to re-add it after each Discord auto-update.

### 4. Capture the four .env values

Drop into `Cascade/asset_pipeline/.env`. `cp .env.example .env` first.

| Key | How to capture |
|---|---|
| `DISCORD_USER_TOKEN` | DevTools (web or desktop) → Console → run the iframe localStorage snippet (below). 70 chars, starts with `MTU`, `MTk`, `OD`, or `Nz`. Treat as password. |
| `MJ_CHANNEL_ID` | Discord Settings → Advanced → Developer Mode ON. Right-click your MJ channel → Copy Channel ID. |
| `MJ_GUILD_ID` | Same trick — right-click the server icon → Copy Server ID. **Required when the MJ channel lives in a guild** (see Gotcha §1). |
| `MJ_IMAGINE_VERSION` | Desktop Discord DevTools → Network. Fire `/imagine <any prompt>` in MJ channel. Find `POST /api/v9/interactions` → Payload → `data.version`. 19-digit number. Re-capture whenever MJ updates the slash command (you'll see `discord 400: This command is outdated`). |
| `MJ_IMAGINE_COMMAND_ID` | Same capture, `data.id`. The default `938956540159881230` is usually stable; only re-capture if you get 404s. |

**Token capture snippet** (paste in Console, Cmd+Shift+M to enable mobile emulation first or this returns undefined):

```javascript
const iframe = document.createElement('iframe');
console.log('Token: %c%s', 'font-size:16px;',
  JSON.parse(document.body.appendChild(iframe).contentWindow.localStorage.token));
iframe.remove();
```

### 5. Apply the guild_id patch to mj_bridge.py

The upstream Cascade `mj_bridge.py` omits `guild_id` from the `/imagine` interaction payload. Discord then treats the call as a DM and returns `discord 400: Unknown Channel, code 10003` for any guild-channel ID. This repo's first bring-up patched the bridge.

Patch (already applied; documenting in case you're setting up on a fresh machine):

```python
# line ~58, after CHANNEL_ID:
GUILD_ID = os.environ.get("MJ_GUILD_ID")  # required when channel is in a guild

# in _send_imagine(), after the payload dict construction, before _post_interaction:
if GUILD_ID:
    payload["guild_id"] = GUILD_ID
return await _post_interaction(payload)
```

The button-press path (`_press_button`) already handles guild_id correctly — only the imagine-fire path needed the fix.

---

## Per-session bring-up

Every time you start working:

```bash
cd /Users/peterlaffey/Documents/Claude/Projects/Cascade/asset_pipeline
/opt/homebrew/bin/python3.11 mj_bridge.py
```

Wait for **`[INFO] Discord connected as <username>`** in the log. Until that line appears, /imagine calls will fail with WebSocket-not-ready errors.

Verify the bridge:

```bash
curl -sS http://127.0.0.1:5000/health
# {"discord_ready": true, "pending_grid": 0, "upscaling": 0, "total_jobs": 0, "output_dir": "..."}
```

The Katybird client doesn't need anything else — it lives in the same machine and hits localhost.

---

## Per-asset generation

### The command

```bash
npx tsx tools/cascade-asset.ts <asset_id> [--upscale all|grid|1|2|3|4]
```

Asset IDs are bound in the source (`tools/cascade-asset.ts` `ASSETS` map). Wave-1 list: `bird`, `clue_a`, `clue_b`, `clue_c`, `region_forest_floor`. To add new asset_ids, edit the map — keep `sref` and `ar` bindings consistent with the Wave-1 pattern.

### Prompt template (locked)

```
<subject> --ar <ratio> --v 7 --style raw --p <moodboard> --sref <character_or_environment_url>
```

- **`--p m7458053701014388751`** — moodboard profile (Architect-built, Sprint 4.0)
- **Character sref** (bird, clues, Katy): `https://cdn.midjourney.com/54cefb43-412a-4931-9895-36cdb2e42a63/0_0.png`
- **Environment sref** (region backdrops): `https://cdn.midjourney.com/4afa7423-2ca6-4862-91db-f8bb4447af8b/0_3.jpeg`

### Subject template — sprite-theme drift prevention

**Lesson from Wave-1 first batch:** the locked srefs alone don't dominate on small natural objects (feathers, scratch marks, keepsakes). MJ falls back to photorealism even with `--style raw`. Fix: bake the aesthetic into every subject explicitly.

Wave-1 subject pattern (from `tools/cascade-asset.ts`):

```
pixel-art sprite of <SUBJECT>, <COMPOSITION HINTS>, low-resolution 2D game sprite,
limited palette, handmade restrained sprite art, readable silhouette, centered,
transparent background
```

Region backdrops swap `transparent background` for the scene composition + `16:9 composed scene`.

The redundant aesthetic phrases (pixel-art / low-resolution / limited palette / handmade / readable silhouette) are intentional — MJ weights repeated concepts higher, and the sref alone needs reinforcement on small subjects.

Per `katybird-combined-spec.md` §6.1–§6.3 and `voice-tone-canon.md`:
- Simple 2D sprite art, handmade and restrained
- Readable silhouettes, limited palettes, expressive but minimal
- Avoid: glossy mobile-game look, over-rendering, photorealism, "cute happy bird" register

### Timeout calibration

`/wait` long-polls until the job hits `done` or `failed`. The Katybird client passes different timeouts based on upscale mode:

| Upscale mode | /wait timeout | Rationale |
|---|---|---|
| `grid` (no upscale) | 180s | Grid alone: 30–90s typical |
| `1` / `2` / `3` / `4` | 360s | Grid + single upscale: 2–4 min |
| `all` | 600s | Grid + 4 upscales: 5–8 min on fast mode, sometimes more |

If you exceed the timeout, **the job keeps running on the bridge** — only the HTTP block ends. Recover via:

```bash
curl -sS http://127.0.0.1:5000/jobs | python3 -m json.tool
# OR for one specific job:
curl -sS http://127.0.0.1:5000/status/<job_id> | python3 -m json.tool
```

### Output locations

- **Raw MJ outputs:** `Cascade/asset_pipeline/generated/<asset_id>.png` (grid) + `<asset_id>_u1.png` ... `_u4.png` (upscales)
- **Promoted assets** (after Architect curation): `assets/bird.png`, `assets/clues/clue_a.png`, `assets/regions/forest_floor.png`
- **Prompt log:** `handoff/cascade-prompts/sprint-4.0.md` (append-only ledger of every roll — exact prompt, job_id, output paths, errors)

---

## Curation workflow

1. Fire asset_id(s) via `npx tsx tools/cascade-asset.ts <id> --upscale all`.
2. Either wait on the HTTP block or fire-and-forget and poll `/jobs` later.
3. When status=`done`, the bridge has 5 files per asset_id: `<id>.png` (grid 2×2), `<id>_u1.png` through `<id>_u4.png` (individual upscales).
4. Architect reviews all four upscales, picks one winner.
5. Move the winner: `cp Cascade/asset_pipeline/generated/<id>_uN.png Katybird/assets/<path>/<id>.png`
6. Wire into Phaser via `PreloadScene` (`this.load.image('bird', '/assets/bird.png')` etc).
7. Run capture + grade to confirm no signal-level drift (the visual swap should be structurally invisible to the contract).
8. If no upscale satisfies, re-roll: re-fire the same `asset_id`. The prompt is deterministic per-id but MJ is non-deterministic per-roll. Logged automatically in `handoff/cascade-prompts/sprint-4.0.md` with timestamps.

The curation gate is Architect-only. Supervisor cannot grade "is this tonally Peter's sprite" — the Rubber Duck Pass surfaces signal-level coherence, not visual taste.

---

## Troubleshooting tree

### `Cannot reach Cascade bridge at http://127.0.0.1:5000`
Bridge isn't running. Start it (see "Per-session bring-up"). If it crashes on import:
- `TypeError: unsupported operand type(s) for |` → Python <3.10. Switch to 3.11.
- `ModuleNotFoundError: No module named 'discord'` → deps installed in wrong Python. Run the `python3.11 -m pip install` line.

### `Cascade bridge is up but Discord is not connected yet`
Wait for `[INFO] Discord connected as <you>` line in bridge log. WebSocket handshake takes 5–15s after process start. If it hangs >60s: check `DISCORD_USER_TOKEN` (a wrong/expired token results in 401 silently — bridge will log it).

### `discord 400: Unknown Channel, code 10003`
Missing `MJ_GUILD_ID` in `.env`. Discord treats `guild_id`-less interactions as DMs. See "One-time setup" §4 to capture it and §5 to verify the patch is applied.

### `discord 400: This command is outdated, please try again in a few minutes`
MJ pushed a new slash command version. Re-capture `MJ_IMAGINE_VERSION` from desktop DevTools (see One-time setup §4). Restart the bridge after editing `.env`.

### `discord 401`
Token expired or rotated. Re-capture `DISCORD_USER_TOKEN` (changing your Discord password invalidates all tokens).

### Job stuck at `submitted` forever
The MJ message never matched the bridge's prompt-substring expectation. Either:
- MJ moderated the prompt — check the channel manually for a different MJ response.
- Your prompt leads with characters that broke the substring matcher. Reword the leading 2–3 words to be more conventional.

### Two jobs swapped
Bridge matches FIFO. Two identical leading prompts fired back-to-back can swap. Include a unique disambiguator in the leading subject (the bridge looks at the prompt's prefix only).

### Photoreal output instead of sprite art
Sref alone isn't enough on small natural objects. Subject must contain explicit "pixel-art sprite", "low-resolution", "limited palette", "handmade restrained" language. See "Subject template" above. If the language still doesn't bite: bump sref weight (`--sref <url>::2` or `::3`) and/or reduce `--s 50` (default 100) to constrain MJ's prettifier.

### `/wait` returns 504 / Timeout
The job kept running on the bridge. Use `/status/<job_id>` to poll without re-firing, or fire again with the calibrated timeout (see "Timeout calibration").

### Bridge restarted mid-job
Bridge tracks jobs in memory. A restart vaporizes in-flight job state. The MJ generation itself continues server-side but the bridge can't surface results. Re-fire after restart.

### MJ ban email
Sacrificial account, per Cascade README's design assumption. Get a fresh account, capture new credentials, restart bridge.

---

## What this runbook does not cover

- **MJ subscription tier / billing.** Outside this loop. Fast-mode 3-concurrent cap is the practical throttle.
- **Tier derivation (image-prompt URL composition).** Cascade README §"Tier derivation" covers it. Katybird Wave-1 doesn't use it; Wave-2 may want it for HUD apology glyphs that derive from a single base glyph.
- **`/blend` command.** Not in the bridge yet. Not needed for Wave-1.
- **iOS App Store sync.** `npx cap sync ios` after `npm run build` repopulates `ios/App/App/public/`. Out of scope until Phase 5 mobile pass.
- **Architectural "why" of the Cascade style stack.** Cascade README §"Style consistency" is the primary; this runbook only restates the Katybird-specific bindings.

---

## MJ techniques — identity-locked variants (Sprint 4.7)

When the goal is "same character, different pose / expression / wings / outfit," using sref + moodboard alone isn't enough — those control *style*, not *identity*. The bird will still drift between generations. Three layers of identity lock available in MJ V7:

### --oref (Omni-Reference) — V7's character/object lock

Replaces V6's `--cref` (which is **not compatible with `--v 7`** — silently rejected). Append to the prompt:

```
<prompt text> --oref <image_url> --ow <weight>
```

- `--ow` (omni-weight): 0 = style only, 100 = default character match, 400 = strict identity preservation, up to 1000 maximum. Bump higher when the default drifts visibly across generations.
- The reference image URL must be publicly fetchable by MJ. Discord CDN URLs from prior generations work; so does anything else MJ can reach.

### Single-image oref, NOT a grid

A 2×2 grid URL as oref makes MJ average identity across 4 variants — you get "different bird every roll" drift. **Use a single-image URL of the curated sprite** (the U-quadrant you already promoted) for tight identity match.

Workflow to get a single-image URL of `assets/bird.png` (or any local file):

```bash
curl -X POST "https://discord.com/api/v9/channels/<MJ_CHANNEL_ID>/messages" \
  -H "Authorization: $DISCORD_USER_TOKEN" \
  -F "files[0]=@assets/bird.png" \
  -F 'payload_json={"content":"katybird canonical bird sprite (oref reference)"}'
```

The response contains `attachments[0].url` — a Discord CDN URL hosting just that single image. Use it as `--oref <url>`.

This was discovered Sprint 4.7 after grid-URL oref gave "bunch of different birds switching in and out of existence" — single-image oref + ow=400 fixed it.

### When oref still drifts

If identity still wanders at ow=400, escalation order:
1. Bump `--ow 1000` (MJ's documented maximum).
2. Re-host the source image with cleaner alpha + tighter crop (less background noise for MJ to interpret).
3. Use MJ's "Vary Region" inpaint on the original image — keeps the body exactly and only alters the prompted region. Requires interactive Discord use (not pipeable through the current bridge).
4. Switch to a layered-sprite approach in Phaser — base body asset + separate wing assets composited at runtime. Highest control, requires per-asset transparent regions cut precisely.

### Implementation in cascade-asset.ts

`AssetSpec` gains optional `oref` (URL) + `ow` (0–1000). `buildPrompt` appends `--oref <url> --ow <weight>` when set. The bridge passes the prompt through to MJ unchanged — no bridge-side change required for v7-specific parameters.

```ts
const OREF_BIRD = "https://cdn.discordapp.com/attachments/<channel>/<id>/bird.png";

bird_wing_up: {
  subject: "the same finch with its wings raised UP in a full upstroke, ...",
  sref: "character",
  ar: "1:1",
  oref: OREF_BIRD,
  ow: 400,
},
```

### When the bridge appears to silently ignore a parameter

If a parameter (like the old `--cref` against `--v 7`) is incompatible with the current MJ version, MJ does NOT return a moderation error. It silently drops the parameter and renders without it. Symptom: the resulting grids look unrelated to the reference. Check current MJ docs for version-compatibility on any reference parameter before pinning a workflow on it.

---

## Workflow — tightening visual scope across rolls

The Sprint 4.7 → 4.7c arc is the worked example: every iteration tightens a different lever. Each step here applies generally, not just to wing animation.

### The tightening levers, in order

1. **Subject language** — the most leverage for low cost. Bake aesthetic and pose constraints into the subject text. Wing-frame Sprint 4.7 needed "SIDE VIEW facing LEFT (matching the reference orientation)" added to the subject before MJ stopped producing forward-facing variants on most rolls. Repeated emphasis ("the same finch...matching the reference orientation") is intentional; MJ weights repeated concepts higher.

2. **Sref + moodboard** — style anchor. Already locked at the start of Sprint 4.0. Don't change once set unless rolling a whole new visual identity.

3. **Oref + ow weight** — character/identity anchor (V7's `--oref`, see prior section). `ow=100` (default) drifts visibly across variants. `ow=400` is the first useful tightness. `ow=1000` (max) is the strongest character lock; use when subject + sref + moodboard aren't enough.

4. **Reference image: grid vs single** — a 2×2 grid as oref makes MJ average identity across 4 variants. Use a single-image URL of the curated U-quadrant. Worked example in the prior MJ techniques section.

### Single-image generation (--upscale 1)

By default MJ returns a 2×2 grid. To get one image per asset (skip curation), pass `--upscale 1`:

```bash
npx tsx tools/cascade-asset.ts bird_wing_up --upscale 1
```

The bridge fires `/imagine`, waits for the grid, presses U1, downloads the upscale as `<asset_id>.png`, saves the grid alongside as `<asset_id>_grid.webp` for reference.

Trade-off: you lose the option to choose between four variants. If `--upscale 1` returns a bad pose, re-roll the whole asset rather than picking a different quadrant. Best when the prompt is tight (subject + sref + moodboard + high-ow oref) — then all 4 grid variants should be similar and U1 is fine.

### Workflow: --upscale 1 vs grid

| Mode | When to use |
|---|---|
| `--upscale 1` (or 2/3/4) | Prompt is tightly constrained (e.g. wing animation with oref + ow=1000). All 4 variants similar → curation is overhead. |
| `--upscale grid` (default) | Exploring an aesthetic, picking from variations, or first-pass for a new asset_id. Use `tools/crop-grid.py <asset_id> <1-4>` to promote a chosen quadrant. |
| `--upscale all` | Generate all 4 upscales for the highest curation quality. Slower (~3-5 min per asset) — use sparingly. |

### crop-grid.py quadrant modes

```bash
python3 tools/crop-grid.py <asset_id> 0   # whole image (single upscale)
python3 tools/crop-grid.py <asset_id> 1-4 # grid quadrant
```

Source detection: tries `<asset_id>.png` (upscale) first, falls back to `<asset_id>.webp` (grid). Alpha-key applies the same in both modes (controlled by `ALPHA_KEY` map per-asset).

### Known operational quirks

- **"U1 press exception" on upscale path.** The bridge logs an exception immediately before the upscale save, but the save succeeds anyway. Documented as a known transient — possibly a race condition in the discord.py-self button-press path. Bridge recovers within ~2s. Safe to ignore unless the save also fails.
- **Upscale extensions differ from grid.** Upscales land as `.png`, grids as `.webp`. `crop-grid.py` handles both via the try-then-fallback file lookup.
- **MJ silently drops version-incompatible parameters.** `--cref` against `--v 7` doesn't error — MJ just ignores it and renders without character reference. Symptom: identity drift you can't explain. Always verify current MJ version compatibility before pinning a workflow on a parameter.

### The iteration loop

For any new generated asset that needs to match an existing one:

1. **Roll one.** Use existing subject + sref + moodboard. No oref yet.
2. **Compare** the result to the canonical reference. If identity drifts, you need an oref.
3. **Host the reference.** Upload the canonical (e.g. `assets/<asset>.png`) to the MJ Discord channel via the curl-to-channel snippet. Capture the CDN URL.
4. **Re-roll with `--oref <url> --ow 100`**. Check identity. If still drifty, escalate ow → 400 → 1000.
5. **Tighten the subject** with orientation / pose / framing constraints if MJ still produces unwanted variants.
6. **Switch to `--upscale 1`** once the prompt is tight enough that all 4 variants are interchangeable. Save a curation round-trip.
7. **Promote with `crop-grid.py <id> 0`** (single-upscale path) or `<id> <1-4>` (grid-quadrant path).

### When the result still misses

If a tightly-constrained prompt still produces off-orientation or off-pose variants, escalation order:

1. Re-roll — MJ has variance run-to-run. Often the next roll lands the constraint.
2. Strengthen the subject with even more emphatic constraints ("MUST be side-view facing left", repeat the key word).
3. Switch back to `--upscale grid` so you can pick the closest-to-target quadrant manually.
4. Use MJ's "Vary Region" inpaint on the canonical asset (interactive Discord, not pipeable through the bridge yet) — keeps the original body exactly and only alters the wing region.
5. Layered Phaser sprites — base body texture + separate wing textures composited at runtime. Highest engine control, requires per-asset transparent regions cut precisely (Photoshop / Procreate).

---

## Lessons surfaced during Sprint 4.0 bring-up

These are the things that weren't in the original handoff (`handoff/phase-4-plan-with-asset-pipeline.md`) and should now be obvious to future-you:

1. **Python version matters.** The bridge requires 3.10+. macOS system Python is 3.9. Pin to `/opt/homebrew/bin/python3.11`. Install bridge deps explicitly: `python3.11 -m pip install -U "discord.py-self" flask requests python-dotenv`.
2. **`MJ_GUILD_ID` is required**, not optional, when MJ lives in a server channel. The Cascade README only listed four .env values; this is the fifth. Without it, `/imagine` returns `discord 400: Unknown Channel, code 10003`.
3. **`/wait` timeout must match the upscale mode**, not be a single fixed value. `--upscale all` blows past the README's 120s default routinely. The Katybird driver defaults to upscale=null (grid only, 180s wait); grids are sufficient for curation, upscales are an opt-in via `--upscale 1..4|all`.
4. **Sref + moodboard is necessary but not sufficient.** Subject language carries 50%+ of the aesthetic gate on small natural objects. Don't rely on the style stack alone. Wave-1 subjects bake in "pixel-art sprite, low-resolution 2D game sprite, limited palette, handmade restrained sprite art, readable silhouette".
5. **MJ ignores "transparent background"** about half the time on sprite-style art. Defensive post-process: alpha-key the four-corner average color in `tools/crop-grid.py` (default ON for character/item asset_ids, OFF for region backdrops). Per-asset toggle lives in the `ALPHA_KEY` dict.
6. **Discord desktop DevTools enable is the unblocker** for `MJ_IMAGINE_VERSION` capture. Web client `/imagine` autocomplete is unreliable; desktop is. The settings.json key name has changed across Discord versions — verify against the maintained `discord-enable-devtools` project before pasting older variants from blog posts. Current correct key: `DANGEROUS_ENABLE_DEVTOOLS_ONLY_ENABLE_IF_YOU_KNOW_WHAT_YOURE_DOING`.
7. **The bridge tracks jobs in memory.** Don't restart it mid-job. If you must, re-fire from the client; MJ-side generation will continue but you lose the wiring.
8. **MJ v7 posts the final grid as a NEW message, not as an edit of the initial preamble.** Upstream `mj_bridge.py` removed jobs from `PENDING_GRID` on the first prompt-substring match (typically the "Waiting to start" preamble) → final grid arrived with a different message_id and got silently ignored → jobs stalled forever at `status: progress`. Patched: `_match_grid` now falls back to scanning in-progress jobs (`status=PROGRESS` AND `grid_path IS NULL`) when no PENDING_GRID match exists. The fix lives in our copy of `mj_bridge.py` and is *not* upstream as of this writing.
9. **Phaser preFX is silent in headless WebKit.** `image.preFX?.addShadow(...)` returns undefined when the FX pipeline isn't available (Canvas renderer, headless software rendering, etc.) and the `?.` swallows the no-op. Drop shadows in headless screenshots will be invisible despite "passing" gates. Use the manual technique (Graphics object with concentric semi-transparent ellipses for blur, or duplicate-Image with tint+alpha for hard shadows) when shadow visibility matters in the observation contract.

## Tools the runbook now relies on

- **`tools/cascade-asset.ts`** — fires a single asset_id at the bridge with the locked prompt template. Default upscale=null. Logs to `handoff/cascade-prompts/sprint-4.0.md`.
- **`tools/crop-grid.py`** — quadrant cropper (`U1..U4` → top-left, top-right, bottom-left, bottom-right) + alpha-keyer + asset promoter. Writes to `Katybird/assets/<destination>/<asset_id>.png`. Requires Pillow.
- **`tools/screenshot.ts`** — Playwright WebKit harness that loads dev server, waits for `__sdd_snapshot()` to include SCENE_RENDERED + HUD_RENDERED + BIRD_RENDERED, captures PNG. Used for the Sprint 4.0 observation contract's screenshot evidence.
- **`tools/capture-headless.ts`** — Existing Node simulator that scripts the playthrough and writes JSONL. Hardcodes clue positions matching `content/main_story/clues.json` — update both when content shifts.

## Decoding screenshots for observation-contract grading

Per `Factory v0 synthesis/sdd-kit-2/TECHNIQUES.md` Visual/UI section: "Deterministic pixel anchors for visual state decoding." Screenshots in `captures/sprint-4.0/` can be sampled mechanically:

```python
from PIL import Image
img = Image.open("captures/sprint-4.0/<run>.png").convert("RGB")
# Sample a 60×14 region under the bird's expected feet position
crop = img.crop((450, 470, 510, 484))
avg = [sum(p[i] for p in crop.getdata())/(60*14) for i in range(3)]
assert sum(avg)/3 < 110, f"shadow patch too bright: {avg}"
```

The Sprint 4.0 card's `## observation contract` enumerates the regions + brightness bands. Future region/region-authoring sprints inherit this pattern.

---

*Living document. Append surfaced issues, calibration changes, and Wave-2+ extensions as they occur.*

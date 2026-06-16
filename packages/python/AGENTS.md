# AGENTS.md

This file follows the [agents.md](https://agents.md) convention — drop it in front of any LLM agent that operates cascade-img. The orientation block below is also the **canonical source** for the per-harness entry files (`CLAUDE.md`, `GEMINI.md`, `.github/copilot-instructions.md`, `.cursor/rules/`, `.windsurfrules`, `.clinerules`): they are generated from it by `packages/python/tools/render_agent_entrypoints.py` and kept in sync by CI. Edit the block here; never edit a generated file by hand.

<!-- AGENT-ORIENTATION:START -->
## What cascade-img is, and how you drive it

**What it is.** cascade-img is an LLM-operable image-generation pipeline — Midjourney through a Discord bridge at v0.1, with pluggable backends (Flux, DALL-E, Imagen, …) behind one interface after. **You, the agent, are its primary operator:** it is built so you compose a prompt, generate, curate the winner, and log the attempt without a human on every roll.

**The loop, per asset.** `compose_prompt → imagine → wait → inspect (read the PNG with vision) → curate (crop_grid → [alpha_key?] → promote) → log_append`. Open each iteration with `read_prompt_log(n=5)` — the append-only log is your working memory across rolls.

**The shape — one daemon, two entry points, all over local HTTP:**
- `cascade-mj-bridge` — the daemon, and the only process that talks to Discord. It must be running.
- `cascade-mcp` — the MCP server exposing 20 tools; this is how you, the agent, drive everything.
- `cascade-mj` — the CLI, for scripting and one-off rolls.

**The 20 MCP tools, by job.** *generation* — `imagine`, `generate_video` (native image→video; composes + fires `--video`/`--loop`/`--motion`/`--end`/`--bs`), `wait`, `status`, `bridge_health`, `mj_action`; *composition* — `compose_prompt`, `compose_video` (build a native image→video prompt without firing); *curation* — `crop_grid`, `alpha_key`, `auto_trim`, `palette_quantize`, `contact_sheet`, `sprite_sheet`, `score_grid`, `video_filmstrip` (sample a video's keyframes into a vision-readable still), `loop_seam_delta` (score how cleanly a `--loop` video closes), `promote`; *working memory* — `log_append`, `read_prompt_log`. Every call returns `{ok, result}` or `{ok: false, error: {code, remediation}}` — branch on the stable `code`, never the message.

**Where to go next.**
- [RUNBOOK.md](./RUNBOOK.md) — install, the Discord `.env` values to capture, bring-up, and every failure mode with its error code and fix. Read this to set up or to recover.
- [CAPABILITIES.md](./CAPABILITIES.md) — every Midjourney prompt parameter and `mj_action`, the V8.1/V7 version split, with ranges and effects.
- [README.md](./README.md) — the overview and why cascade-img exists.
- [examples/](./examples/) — two end-to-end walkthroughs: one image, and a batch sharing one style.
- [AGENT_RUNDOWN.md](./AGENT_RUNDOWN.md) — a paste-in prompt that has an LLM read the source and brief you from it.

**The one constraint.** cascade-img drives Midjourney through a Discord *user* account; both services' Terms of Service prohibit that automation, and the human who configured the daemon has acknowledged it. Treat a persistent token rejection (`DISCORD_401` after re-capture, or `DISCORD_RECONNECT_FAILED(reason=auth)`) as a structural failure that needs the human — the daemon cannot self-recover.
<!-- AGENT-ORIENTATION:END -->

## How to operate in this repo

Two working habits — borrowed from how this project is maintained — that make you a better operator here.

**Read in full.** When this guide, the [RUNBOOK](./RUNBOOK.md), or the person you're helping points you at a file, doc, or folder, read the whole thing — not an excerpt, not the first screen, no `offset`/`limit`, and don't hand the read off to a sub-agent that returns only snippets. The parts that strand an operator (the Discord token capture, the env vars, each error's remediation) live in the details, so a half-read of the RUNBOOK is how setup fails. If a set is genuinely too large to read at once, stop and say which files and how big, rather than skimming or silently truncating.

**Reverse-explain — bridge to the person.** Most people running cascade-img through you are not engineers; bridging the tool to them is part of the job. When you explain a step or a term (what a moodboard is, why the bridge has to stay running, what "upscale" means), expose just enough of the surrounding context to make it land at their level — scope-correct, not maximal. Backfill the one prior idea they need, or compress a detail up into its parent concept; don't dump the whole dependency graph, and don't leave a term undefined that the next step depends on. Good explanation is dependency management under scope control.

## The loop

The agent's job, per asset:

```
1. compose:  build the prompt from its parts (subject + style + identity + aspect ratio)
2. fire:     imagine(prompt, asset_id, upscale)              → job_id
3. wait:     wait(job_id, timeout=180|360|600)               → job record
4. inspect:  read the PNG at job.image_path with vision
5. decide:   promote / re-roll / escalate ow / give up + ask human
6. curate:   crop_grid → [alpha_key]? → promote   (if decision = promote)
              alpha_key is OPTIONAL — apply only when transparency is wanted
              and only when keyed_ratio lands in the healthy band (0.1-0.9)
7. log:      log_append(asset_id, prompt, job_id, outputs, agent_decision, agent_reason)

next loop iteration starts with read_prompt_log(n=5) for working memory
```

The cycle is closeable end-to-end without human intervention for the common case. Human is needed for:

- Initial guidance (moodboard ID, style reference / sref, optional oref reference)
- Failure modes flagged "escalate" below
- Final acceptance of the asset set

## Tools

Available via the `cascade-mcp` MCP server. Each returns `{ok: bool, result: ...}` on success or `{ok: false, error: {code, message, remediation?}}` on failure.

| tool | purpose |
|---|---|
| `compose_prompt(subject, constraints, moodboard, sref, stylize, style_raw, oref, ow, aspect_ratio, version, hd, sd, …)` | Build a Midjourney prompt string from structured parts. `version` defaults to `"8.1"`; use `"7"` for `oref`/`quality` |
| `compose_video(image_url, text, motion, raw, loop, end_frame, batch_size)` | Build a native image→video prompt (`--video` + `--loop`/`--motion`/`--end`/`--bs`). Video params only; `loop`/`end_frame` are mutually exclusive |
| `imagine(prompt, asset_id, upscale)` | Fire the prompt at the bridge; returns `job_id` |
| `generate_video(image_url, asset_id, text, motion, raw, loop, end_frame, batch_size)` | Compose + fire a native image→video generation in one call; returns `job_id` (poll with `wait`; result is an animated webp) |
| `wait(job_id, timeout)` | Block until `done` or `failed` |
| `status(job_id)` | Non-blocking status read |
| `bridge_health()` | Is the daemon running? Is Discord connected? |
| `mj_action(job_id, action, slot=None)` | Press a response-message button on a completed job's **upscaled** image (see below). `slot` (1-4) targets a specific image when the job ran `upscale="all"`; omit it for the canonical one. Needs an upscaled image first. |
| `crop_grid(src, quadrant, dest)` | Pull one quadrant from a 2x2 grid (0 = whole) |
| `score_grid(src)` | Rank a grid's four quadrants on sharpness/contrast/edge-density so you pick on evidence before reading with vision |
| `video_filmstrip(src, dest, frames)` | Sample a video's keyframes into one labelled still + return its signature (frame_count/duration/fps) — read a video with vision the way you read a grid |
| `loop_seam_delta(src)` | Score how cleanly a `--loop` video closes (0-1 last-vs-first-frame distance; ~0 = seamless) |
| `contact_sheet(src, dest, labels)` | Composite a 2x2 grid into one labelled sheet — a better single input for vision selection than four separate reads |
| `alpha_key(src, dest, tolerance, method)` | Corner-anchored alpha-key. `method="flood"` (default; correct for a subject on a uniform background), `"threshold"`, or `"rembg"` (ML; needs the `[ml]` extra). Returns `keyed_ratio` so you can detect failure. |
| `auto_trim(src, dest, mode, tolerance)` | Crop to the content bounding box (`mode="alpha"` after alpha_key, or `"color"`) |
| `palette_quantize(src, dest, n_colors, method)` | Reduce to a fixed palette for the limited-palette look |
| `sprite_sheet(srcs, dest, layout, padding)` | Pack several curated cut-outs into one sheet/atlas + a `.frames.json` map |
| `promote(src, dest)` | Copy curated asset to project tree |
| `log_append(asset_id, prompt, backend, job_id, upscale, outputs, error, agent_decision, agent_reason)` | Append a record to the working-memory log |
| `read_prompt_log(n)` | Read structured log entries (defaults to all) |

Output paths from `imagine` + `wait` are deterministic: `{output_dir}/{asset_id}.{png,webp}` for the grid, `_u1..u4.png` for upscales. You can compute the path before the call returns.

## Driving the response-message buttons

A finished upscale carries the buttons a human would otherwise click in Discord. `mj_action(job_id, action, slot=None)` presses them for you — no human, no clicking. It requires the job to have an **upscaled** image (run `imagine` with `upscale=1-4` or `"all"` first); on a grid-only job it returns `error.code == "NO_UPSCALED_IMAGE"`. When the job ran `upscale="all"`, pass `slot=1-4` to act on a specific one of the four images; omit `slot` for the canonical image (the first upscale that landed).

`action` is one of:

- **Re-upscale**: `upscale_subtle`, `upscale_creative`
- **Vary**: `vary_subtle`, `vary_strong`
- **Zoom out**: `zoom_out_2x`, `zoom_out_1_5x`
- **Pan**: `pan_left`, `pan_right`, `pan_up`, `pan_down`
- **Animate** (image → video): `animate_high`, `animate_low`
- **Favorite**: `favorite`

On a **`generate_video` job** (not an upscaled image), `action` is instead one of the native-video result buttons:

- **Video upscale** (extract a slot as a standalone clip — the video `U1`-`U4`): `video_upscale` with `slot=1-4`
- **Extend** (lengthen a SOLO clip ~4s): `extend_high`, `extend_low` with the `slot` you upscaled

Press `video_upscale` first; when its SOLO clip lands, the bridge emits `MJ_ACTION_SURFACE_REGISTERED` and records that slot as an extendable surface, so `extend_*` on the same slot then works (the slot round-trips — MJ's SOLO extend buttons are grid-aligned). Calling `extend_*` before `video_upscale` returns `NO_UPSCALED_IMAGE` telling you to upscale first. To re-roll a video, call `generate_video` again (the grid's re-roll button is not exposed — its untracked result can perturb job routing).

The pressed action's result — a new grid for vary/zoom/pan, a single image for `upscale_*`, a short animation for `animate_*`, an mp4 for `video_upscale`/`extend_*` — is routed back to the originating job automatically: the bridge downloads it and appends an entry to the job's `derived` list (`{action_kind, mj_uuid, path, content_type, ...}`), which you read via `status(job_id)`. `animate_*` arrives as an animated WebP (`image/webp`, ~125 frames), not an mp4; `video_upscale`/`extend_*` arrive as mp4 (`action_kind="animation"`). `favorite` only rates the image — it produces no artifact, so nothing lands in `derived`. With `upscale="all"` every per-slot image is actionable and a derived result replying to any of them routes home. (Known v0.1 limit: a derived result that is itself a grid — vary/zoom/pan — is recorded in `derived` but not re-tracked as a new job, so you can't then `mj_action` on its quadrants.)

## Prompt parts

cascade-img is **version-aware** and defaults to **Midjourney V8.1** (MJ's default
since 2026-06-11). Set `version` to `"8.1"` (default), `"8"`, or `"7"`. V8.1
dropped some V7 features, so the composer gates them and fails loudly on a
mismatch: **`oref`/`ow` and `quality` are V7-only** (set `version="7"`), and
**`hd`/`sd` are V8.1-only**. Everything else works on both.

The composer assembles these into the prompt string. The most-used:

- **Subject**: the literal subject sentence + optional `constraints` list (folded in for emphasis — MJ weights repeated concepts higher).
- **Moodboard (`--p`)**: MJ's personalization profile code. Human supplies once.
- **Sref (`--sref`)**: style-reference URL or integer code. Human supplies once.
- **Stylize (`--s`)**: 0-1000. Default 100 in MJ; lower constrains MJ's stylization and lets the sref dominate.
- **Style raw**: toggles `--style raw`. Default on for cascade-img's locked-style use case.
- **Oref (`--oref`)** / **Ow (`--ow`)**: omni-reference identity lock (single-image URL, not a grid) and its weight (0-1000; 100 loose, 400 tight, 1000 max). **V7 only** — requires `version="7"`; V8.1 does not support Omni Reference.
- **Aspect ratio (`--ar`)**: "1:1", "16:9", "9:16", etc.
- **Version (`--v`)**: `"8.1"` (default), `"8"`, or `"7"`.

The composer also accepts `sw` (`--sw` style weight, only with `sref`), `negatives` (`--no`), image prompts + `image_weight` (`--iw`), the render-control params `tile`, `exp` (`--exp` experimental aesthetics), `chaos`, `weird`, `seed`, the **V7-only** `quality` (`--q`), and the **V8.1-only** `hd`/`sd` (native 2048px / 1024px). **[CAPABILITIES.md](./CAPABILITIES.md) is the complete reference** — every part, its range, the per-version split, every `mj_action`, and the features intentionally not wired (draft mode, `--repeat`, GPU/stealth modes, …).

## Holding a non-photoreal style

Sref + moodboard alone often don't dominate, especially on small or natural subjects — MJ falls back to photorealism even with `--style raw`. Whatever look you want (flat vector, pixel-art sprite, watercolor, line art), name it in the subject and repeat its key descriptors. For example, for a pixel-art game sprite:

```
"pixel-art sprite of <subject>, low-resolution 2D game sprite,
limited palette, handmade restrained sprite art, readable silhouette,
centered, transparent background"
```

The redundancy is intentional — swap the descriptors for your target style. Full-scene images (backgrounds, landscapes) drop "transparent background" and add scene framing like "16:9 composed scene".

## Identity lock

When you need "same subject, different pose/angle/expression":

1. Start with `oref` set to a **single-image URL** of the canonical reference (not a 2x2 grid URL — that averages identity across 4 variants).
2. `ow=100` is the default; if identity drifts visibly, escalate `ow=400`, then `ow=1000`.
3. Add orientation/composition constraints to the subject (e.g. "side view facing left, matching the reference orientation") — MJ frequently disregards orientation without explicit emphasis.
4. If identity still wanders at `ow=1000`: re-host the source image with cleaner alpha and tighter crop, or escalate to the human for a layered/composited approach.

## Failure modes you should branch on

Every error returned to you carries a stable `code`. The codes that matter for the loop:

| code | what it means | what you do |
|---|---|---|
| `DISCORD_400_OUTDATED` | MJ updated the slash command | escalate to human — needs `MJ_IMAGINE_VERSION` re-capture |
| `MISSING_*` | env var not set | escalate to human — one-time setup gap |
| `DISCORD_401` | token expired | escalate to human — token re-capture |
| `DISCORD_NOT_READY` (HTTP 503) | bridge's WebSocket dropped, reconnect in flight | retry after a short delay; the daemon auto-reconnects with exponential backoff |
| `MJ_UUID_MISSING` | grid arrived without U1-U4 buttons | re-roll once; if reproducible, escalate |
| `GRID_DOWNLOAD_FAILED` / `UPSCALE_DOWNLOAD_FAILED` | network blip during PNG fetch | re-roll automatically |
| `UPSCALE_BUTTON_FAILED` / `UPSCALE_ALL_BUTTONS_FAILED` | transient Discord interaction error on the U-button press | re-roll the imagine |
| `NO_UPSCALED_IMAGE` (HTTP 409) | `mj_action` on a job with no upscaled image | upscale a quadrant first, then retry the action |
| `BUTTON_NOT_FOUND` (HTTP 404) | the requested action's button isn't on this image | MJ may not offer it for this image/version — pick another action or skip |

A `/imagine` that returns HTTP 202 with `status: "submitted_unconfirmed"` is NOT a failure — the Discord interaction took longer than 35s but MJ may have processed it. Poll `/wait` for the actual outcome. DO NOT re-fire `/imagine` for the same asset before `/wait` resolves; that would double-bill if MJ processed the original.

`imagine` accepts an optional `idempotency_key`. Pass one (any unique string, e.g. a UUID you generate per attempt) and reuse it on a retry of the *same* attempt: if the original submission actually landed, the bridge replays the existing job (`idempotent_replay: true` in the response) instead of submitting and billing again. Use a fresh key (or none) for a deliberate re-roll — the key dedupes retries, not assets.

Everything else (generic backend exceptions, timeouts): re-roll up to N times (3 is a reasonable default), then escalate.

## When to ask the human

The human's preference about involvement comes first. If they've asked to see the grids, to pick the quadrant themselves, or to sign off on a step, do that — wanting to be looped in always beats your autonomy. Check what they want before deciding things on their behalf.

Absent that, you're capable of deciding these on your own, so don't reflexively ask:

- Which quadrant of a grid is best — you can read the PNG with vision and pick. But if the human would rather see the grid and choose, show it to them and let them.
- Whether to re-roll — apply the policy above.
- Whether to alpha-key — read the cropped PNG; if it needs transparency, call `alpha_key` (default `method="flood"`, `tolerance=24`). The tool envelope returns `keyed_ratio`. Healthy band is 0.1-0.9. Under 0.1 means the keyer found no background (swap `method="threshold"` or skip alpha-key). Over 0.9 means it keyed out the subject itself (reject and reroll with higher-contrast composition, or skip alpha-key for this asset).

You should ask the human for:

- Initial moodboard ID, style-reference (sref) URL, and (if doing identity-locked variants) an oref reference image.
- Acceptance of the final asset set.
- Recovery from any `escalate` failure mode above.
- Tonal judgment calls where stakes exceed mechanical "is the output well-formed" checks.

## Routing is collision-resistant; you can submit similar prompts safely

Every `/imagine` submission gets a per-job request token appended to the prompt as `--no cscidnocollide{token}`. The bridge matches MJ's echoed grid messages on this token, not on prompt substrings. You can fire two prompts with identical leading text back-to-back without grid messages being mis-routed.

## The prompt log is your working memory

`read_prompt_log(n=5)` returns the last 5 records as structured dicts. Read it at the top of each loop iteration to know what you've already tried for the current asset_id. Write to it via `log_append` after every roll, including failures — the next iteration's read depends on yours having been written.

Fields per record:

```json
{
  "ts": "2026-...Z",
  "asset_id": "mountain-icon",
  "prompt": "...",
  "backend": "midjourney_discord",
  "job_id": "...",
  "upscale": "1" | "all" | null,
  "outputs": { "image_path": "...", "grid_path": "...", "upscales": {...} },
  "error": null | "...",
  "agent_decision": "promote" | "reroll" | "escalate" | null,
  "agent_reason": "freeform — one sentence, what informed the call"
}
```

`agent_reason` is for you, not the human. Be specific. "U2 matches identity lock and aesthetic" beats "looks good". Future-you reads this on the next iteration.

## ToS context

cascade-img drives Midjourney through a Discord user account. Both Discord's and Midjourney's Terms of Service prohibit user-account automation; the human operating cascade-img has acknowledged this when they configured the daemon. Surface a token-rejected failure (`DISCORD_401` that persists after re-capture, or `DISCORD_RECONNECT_FAILED(reason=auth)`) as a structural failure that needs the human to act — the daemon can't recover on its own.

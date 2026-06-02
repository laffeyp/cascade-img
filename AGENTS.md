# AGENTS.md

Drop this in front of any LLM agent that needs to operate cascade-img. The file follows the [agents.md](https://agents.md) convention.

## What cascade-img is

A Python package and an MCP server that let an LLM agent generate, curate, and log Midjourney images autonomously through a Discord self-bot bridge. v0.1 ships the MJ backend; v0.2+ adds Flux, DALL-E, Imagen, etc. behind the same interface.

You — the agent — are the primary user. Everything below is shaped around what you need to drive the loop without a human in the room for every roll.

## The loop

The agent's job, per asset:

```
1. compose:  build the prompt from facets (subject + style stack + identity stack + ar)
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

- Initial guidance (moodboard ID, character sref, optional oref reference)
- Failure modes flagged "escalate" below
- Final acceptance of the asset set

## Tools

Available via the `cascade-mcp` MCP server. Each returns `{ok: bool, result: ...}` on success or `{ok: false, error: {code, message, remediation?}}` on failure.

| tool | purpose |
|---|---|
| `compose_prompt(subject, constraints, moodboard, sref, stylize, style_raw, oref, ow, aspect_ratio)` | Build a v7 prompt string from structured facets |
| `imagine(prompt, asset_id, upscale)` | Fire the prompt at the bridge; returns `job_id` |
| `wait(job_id, timeout)` | Block until `done` or `failed` |
| `status(job_id)` | Non-blocking status read |
| `bridge_health()` | Is the daemon running? Is Discord connected? |
| `crop_grid(src, quadrant, dest)` | Pull one quadrant from a 2x2 grid (0 = whole) |
| `alpha_key(src, dest, tolerance, method)` | Corner-anchored alpha-key. `method="flood"` (default; correct for sprite-on-uniform-bg) or `method="threshold"`. Returns `keyed_ratio` so you can detect failure. |
| `promote(src, dest)` | Copy curated asset to project tree |
| `log_append(asset_id, prompt, backend, job_id, upscale, outputs, error, agent_decision, agent_reason)` | Append a record to the working-memory log |
| `read_prompt_log(n)` | Read structured log entries (defaults to all) |

Output paths from `imagine` + `wait` are deterministic: `{output_dir}/{asset_id}.{png,webp}` for the grid, `_u1..u4.png` for upscales. You can compute the path before the call returns.

## V7 facets

The composer assembles these into the prompt string:

- **Subject**: the literal subject sentence + optional `constraints` list (folded in for emphasis — MJ weights repeated concepts higher).
- **Moodboard (`--p`)**: MJ's personalization profile code. Human supplies once.
- **Sref (`--sref`)**: style-reference URL or integer code. Human supplies once.
- **Stylize (`--s`)**: 0-1000. Default 100 in MJ; lower constrains MJ's prettifier and lets the sref dominate.
- **Style raw**: toggles `--style raw`. Default on for cascade-img's locked-style use case.
- **Oref (`--oref`)**: V7 omni-reference identity lock. URL to a single image (not a grid).
- **Ow (`--ow`)**: omni-weight, 0-1000. 100 default (loose), 400 tight identity, 1000 max.
- **Aspect ratio (`--ar`)**: "1:1", "16:9", "9:16", etc.

## Sprite-style register

Sref + moodboard alone don't dominate on small natural objects (feathers, scratch marks, keepsakes) — MJ falls back to photorealism even with `--style raw`. Bake the aesthetic into the subject explicitly:

```
"pixel-art sprite of <subject>, low-resolution 2D game sprite,
limited palette, handmade restrained sprite art, readable silhouette,
centered, transparent background"
```

The redundancy is intentional. Region backdrops (full scenes) drop "transparent background" and add "16:9 composed scene".

## Identity lock

When you need "same character, different pose":

1. Start with `oref` set to a **single-image URL** of the canonical sprite (not a 2x2 grid URL — that averages identity across 4 variants).
2. `ow=100` is the default; if identity drifts visibly, escalate `ow=400`, then `ow=1000`.
3. Add orientation constraints to the subject ("SIDE VIEW facing LEFT (matching the reference orientation)") — MJ frequently disregards orientation without explicit emphasis.
4. If identity still wanders at `ow=1000`: re-host the source image with cleaner alpha and tighter crop, or escalate to the human for a layered-sprite approach.

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

A `/imagine` that returns HTTP 202 with `status: "submitted_unconfirmed"` is NOT a failure — the Discord interaction took longer than 35s but MJ may have processed it. Poll `/wait` for the actual outcome. DO NOT re-fire `/imagine` for the same asset before `/wait` resolves; that would double-bill if MJ processed the original.

Everything else (generic backend exceptions, timeouts): re-roll up to N times (3 is a reasonable default), then escalate.

## When to ask the human

You should not ask the human for:

- Which quadrant of a grid is best — read the PNG with vision and decide.
- Whether to re-roll — apply the policy above.
- Whether to alpha-key — read the cropped PNG; if it needs transparency, call `alpha_key` (default `method="flood"`, `tolerance=24`). The tool envelope returns `keyed_ratio`. Healthy band is 0.1-0.9. Under 0.1 means the keyer found no background (swap `method="threshold"` or skip alpha-key). Over 0.9 means it ate the subject (reject and reroll with higher-contrast composition, or skip alpha-key for this asset).

You should ask the human for:

- Initial moodboard ID, character sref URL, and (if doing identity-locked variants) an oref reference image.
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
  "asset_id": "bird",
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

## ToS posture

You are driving an unsanctioned channel against Midjourney. The human knows this; it is in [TOS.md](./TOS.md) and the README's first paragraph. Do not surface ToS warnings to the human in the loop — they have already opted in. Do surface ban notifications (`DISCORD_401` persistent after token re-capture) as a structural failure that needs the human to provision a new account.

---

*The mark is recognition, not insight.*

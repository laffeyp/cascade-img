# Capabilities

Exactly which Midjourney features cascade-img drives, and what each one does.
This is the single source of truth; the `compose_prompt` MCP tool's JSON schema
and `MIDJOURNEY_DISCORD_CAPABILITIES` (in `bridge_client.py`) mirror it.

**Version stance.** cascade-img is **version-aware** and defaults to **Midjourney
V8.1** — MJ's default model since 2026-06-11. The composer's `version` accepts
`"8.1"` (default), `"8"`, or `"7"`; pick the version per generation (the MCP
`compose_prompt` tool, the `cascade-mj` registry, and `PromptComposer.compose`
all take it).

**Why V7 is still here.** V8.1 dropped several V7 features — most importantly
**Omni Reference (`--oref`/`--ow`)**, cascade-img's identity lock, which is
**V7-only** (MJ silently downgrades an oref prompt to V7; the composer makes that
explicit instead). Set `version="7"` whenever you need identity lock or `--q`.

**Feature support is gated by version** and the composer fails loudly on a
mismatch rather than letting MJ reject or silently rewrite the render (the
external-grammar trap). The split below is grounded in Midjourney's own Version
compatibility chart ([docs](https://docs.midjourney.com/hc/en-us/articles/32199405667853-Version),
updated 2026-06-11):

- **Both V7 and V8.1:** `--ar`, `--style raw`, `--p`, `--sref`, `--sw`, `--s`,
  `--no`, `--tile`, `--exp`, `--chaos`, `--weird`, `--seed`, `--iw`, image prompts.
- **V7 only:** `--oref`/`--ow` (Omni Reference), `--q` (Quality).
- **V8.1 only:** `--hd` (native 2048px) / `--sd` (1024px).

Midjourney changes its parameter surface over time; this reflects V8.1/V7 as of
mid-2026. If a flag stops working, check Midjourney's
[Parameter List](https://docs.midjourney.com/hc/en-us/articles/32859204029709-Parameter-List)
and [Version](https://docs.midjourney.com/hc/en-us/articles/32199405667853-Version) pages.

---

## Prompt composition (`compose_prompt` / `cascade-mj` registry)

Every part below is optional except `subject`. Ranges are validated at
construction, so a bad value fails before it reaches Midjourney.

| Part | Midjourney flag | Range / values | What it does |
|---|---|---|---|
| `subject` | (prompt body) | non-empty text | The thing to depict. Required. |
| `constraints` | (folded into body) | list of phrases | Comma-appended to the subject; Midjourney weights repeated concepts higher, so naming style traits explicitly pulls harder than one phrase. |
| `aspect_ratio` | `--ar` | `1:1`, `16:9`, `9:16`, `4:3`, `3:4`, `2:3`, `3:2` | Output aspect ratio. Default `1:1`. |
| `moodboard` | `--p` | personalization profile code | Applies a saved Midjourney personalization/moodboard profile. |
| `sref` | `--sref` | style-reference URL or code | Steers the output toward a reference style. |
| `sw` | `--sw` | 0–1000 (default 100) | Style weight: how strongly the `sref` pulls. Only meaningful with `sref`. |
| `stylize` | `--s` | 0–1000 | Strength of Midjourney's default aesthetic. Lower lets the `sref` dominate. |
| `style_raw` | `--style raw` | on/off (default on) | Suppresses Midjourney's automatic style adjustments. |
| `oref` | `--oref` | single-image URL | Omni-reference: the identity lock — "same subject, new pose/angle". **V7 only** (requires `version="7"`); V8.1 does not support it. |
| `ow` | `--ow` | 0–1000 (default 100) | Omni-weight: how tightly to hold the `oref` identity. **V7 only.** |
| `negatives` | `--no` | list of phrases | Things to suppress (text, watermarks, extra limbs). Emitted as the final flag. |
| `image_prompts` | (leading URLs) | list of image URLs | Reference images Midjourney blends in; emitted before the subject. |
| `image_weight` | `--iw` | 0–3 | How strongly the image prompts pull. Meaningless without `image_prompts`. |
| `tile` | `--tile` | on/off | Seamless, repeating output. |
| `exp` | `--exp` | 0–100 (whole number) | Experimental aesthetics — more detail/dynamism. Above ~25 can overwhelm `stylize`/`p`. |
| `chaos` | `--chaos` | 0–100 | Variety across the four grid candidates. |
| `weird` | `--weird` | 0–3000 | Offbeat / unconventional aesthetics. |
| `quality` | `--q` | 1, 2, or 4 | GPU-cost lever on the initial grid (no `--q 3`). **V7 only** (requires `version="7"`); V8.1 uses `hd`/`sd` instead. |
| `hd` | `--hd` | on/off | **V8.1 only.** Native 2048×2048 render, no separate upscale step (~1.3 GPU-min). Mutually exclusive with `sd`. |
| `sd` | `--sd` | on/off | **V8.1 only.** Native 1024×1024 render (~0.8 GPU-min). Mutually exclusive with `hd`. |
| `seed` | `--seed` | 0–4294967295 | Near-reproducibility within a fixed model + params. |
| `version` | `--v` | `8.1` (default), `8`, `7` | Midjourney model version. Default `8.1`; use `7` for the `oref` identity lock and `--q`. |

`--v <version>` is always emitted (default `--v 8.1`); set `version` to choose the
model. The composer rejects a version/feature mismatch (e.g. `oref` on V8.1) at
construction rather than letting the render fail or silently switch models.

---

## Response-message actions (`mj_action(job_id, action, slot=None)`)

These press the buttons Midjourney puts on a finished **upscaled** image — no
human clicking. The job must have an upscaled image first (`upscale=1-4` or
`"all"`); a grid-only job returns `NO_UPSCALED_IMAGE`. With `upscale="all"`, pass
`slot=1-4` to act on a specific one of the four images. The result is downloaded
and recorded on the job's `derived` list, read via `status(job_id)`.

| Action | What it does | Result |
|---|---|---|
| `upscale_subtle` / `upscale_creative` | Re-upscale 2× (subtle keeps detail; creative adds it) | a single image |
| `vary_subtle` / `vary_strong` | Generate variations (low / high deviation) | a new 2×2 grid |
| `zoom_out_2x` / `zoom_out_1_5x` | Outpaint outward (zoom out) | a new 2×2 grid |
| `pan_left` / `pan_right` / `pan_up` / `pan_down` | Outpaint in a direction | a new 2×2 grid |
| `animate_high` / `animate_low` | Image → video (high / low motion) | an animated WebP (`image/webp`, ~125 frames / ~5s), not an mp4 |
| `favorite` | Bookmark the image in Midjourney | no artifact (no-op for the pipeline) |

> Known v0.1 limit: a derived result that is itself a grid (vary/zoom/pan) is
> recorded in `derived` but not re-tracked as a new job, so you can't then
> `mj_action` on its quadrants.

> **V8.1 action surface (verified live against real MJ, 2026-06-14).** On a V8.1
> render, `vary_*`, `zoom_out_*`, `pan_*`, `animate_*`, `favorite`, and the grid
> `U1`-`U4` upscales (`upscale=1-4`/`"all"`) **all work**. The **only** action
> that is **V7-only** is the Subtle/Creative **re-upscale** (`upscale_subtle` /
> `upscale_creative`): V8.1 renders native 2K via `--hd`, so the 2× re-upscale
> step is gone — pressing it on a V8.1 image returns a clean
> `no '<action>' button found` error. For higher resolution on V8.1, use `hd`;
> for the Subtle/Creative re-upscale specifically, render on V7.

---

## Video prompt composition (`compose_video`)

Midjourney turns a starting image into a ~5-second video (delivered as an
animated `.webp`). cascade-img reaches this two ways:

- **From a generated upscale:** `mj_action(job_id, "animate_high" |
  "animate_low")` presses the Animate button on a finished upscale — image →
  video, downloaded to `derived`. High/Low motion only; no loop/end/batch.
- **Native video generation (`generate_video`):** compose + fire a video prompt
  from your own starting image with the full video param surface, in one call —
  `generate_video(image_url, asset_id, loop=…, motion=…, end_frame=…,
  batch_size=…)` returns a `job_id` you poll with `wait` (result is the animated
  webp). `compose_video(...)` builds the same prompt without firing. A video
  prompt carries **only** video-specific params (MJ strips image params under
  `--video`):

| Part | Midjourney flag | Values | What it does |
|---|---|---|---|
| `image_url` | (leading URL) | image URL | The starting frame. Required; leads the prompt. |
| `text` | (prompt body) | text | Optional motion/scene description. |
| (always) | `--video` | — | Marks this as a native video generation. |
| `motion` | `--motion` | `low` (default) / `high` | Camera/subject motion amount. |
| `raw` | `--raw` | on/off | Tighter prompt adherence, less added flair. |
| `loop` | `--loop` | on/off | **Looping video** — reuse the start frame as the end frame. |
| `end_frame` | `--end` | image URL | A *different* end frame. Mutually exclusive with `loop`. |
| `batch_size` | `--bs` | 1, 2, 4 | How many videos to generate per prompt. |

> Routing note: a video prompt can't carry cascade-img's `--no` routing token,
> so the bridge binds the job to the `s.mj.run/…` short URL Midjourney mints in
> its "Creating video…" ack and routes the result on that.

**Inspecting a video.** A video isn't readable by vision the way a still is, so
two curation tools make it legible:

- `video_filmstrip(src, dest, frames)` — sample the video's keyframes into one
  labelled still you read with vision, plus a signature (`frame_count`,
  `duration_s`, `fps`, dims). `duration_s`/`fps` are best-effort.
- `loop_seam_delta(src)` — for a `--loop` video, the 0–1 distance between the
  last and first frames (~0 = seamless). A quality number, not an eyeball.

**Video result actions (`mj_action` on a `generate_video` job).** A finished
native-video grid carries `video_virtual_upscale` buttons, and each extracted clip
carries extend buttons. Press them by passing the **video** `job_id` to `mj_action`:

| Action | Acts on | What it does | Result |
|---|---|---|---|
| `video_upscale` | the video grid (`slot=1-4`) | Extract one slot as a standalone clip — the video `U1`-`U4` | a single mp4 (~720p), recorded in `derived` as `animation` |
| `extend_high` / `extend_low` | a SOLO clip (`slot=N`) | Lengthen that clip by ~4s (high / low motion) | an extended mp4, recorded in `derived` |

Order matters: `extend_*` acts on a SOLO clip, so press `video_upscale` on a
slot first. That landing emits `MJ_ACTION_SURFACE_REGISTERED` (slot, message id,
`surface_kind=video_solo`) and records the clip as an extendable surface; calling
`extend_*` before any `video_upscale` returns `NO_UPSCALED_IMAGE` with a remediation
that says to press `video_upscale` first. MJ's SOLO extend buttons are grid-aligned
(`video_virtual_upscale::2` → `animate_*_extend::2`), so slot N round-trips — verified
live for slots 1 and 2. The whole chain — `generate_video` → `video_upscale` →
`extend_high` — is verified live against real MJ (2026-06-15).

> The grid's **re-roll** button is deliberately not exposed as an action. It
> generates a fresh, untracked video whose own `--video` short-URL ack would be
> claimed by the bind-on-vendor-echo matcher and could mis-bind a pending
> `generate_video` job — regenerate by calling `generate_video` again instead, which
> is tracked and serialized.

---

## Not wired yet (real features cascade-img doesn't expose at v0.1)

Intentionally out of scope for v0.1 — listed so the boundary is explicit rather
than implied:

- **Draft Mode (`--draft`).** Faster, cheaper draft renders — but it changes the
  render/button flow (draft → enhance), so it's not a drop-in flag; deferred.
  **V7 only** (V8.1 does not support `--draft`).
- **GPU mode** (fast / relax / turbo) and **Stealth** (`--stealth`, private
  renders). cascade-img uses the account's default mode. (V8.1 does not support
  Turbo.)
- **`--repeat`** (fire the same prompt N times in one call).
- **Video SD/HD resolution** — a settings-panel toggle, not a prompt flag, so
  it's not exposed. (Native video *generation* and its result buttons —
  `video_upscale` / `extend_*` — ARE wired; see "Video result actions" above.
  The grid's re-roll button is deliberately deferred — regenerate via
  `generate_video` instead.)
- **Character Reference (`--cref` / `--cw`).** Superseded by Omni Reference
  (`--oref` / `--ow`, V7-only), which **is** supported on V7.
- **`--stop`.** A v6 parameter; **v7+ rejects it** ("--stop is not compatible with
  --version 7"), so it's not exposed.

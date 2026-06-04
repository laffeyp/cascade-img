# Capabilities

Exactly which Midjourney features cascade-img drives, and what each one does.
This is the single source of truth; the `compose_prompt` MCP tool's JSON schema
and `MIDJOURNEY_DISCORD_CAPABILITIES` (in `bridge_client.py`) mirror it.

**Version stance.** cascade-img targets **Midjourney v7 only** — every prompt is
emitted with `--v 7`. This is deliberate: v7 is the current model, and there's no
reason to render on an older one, so version selection and back-support for older
versions' features are intentionally not provided.

Midjourney changes its parameter surface over time; this reflects v7 as of
mid-2026. If a flag stops working, check Midjourney's
[Parameter List](https://docs.midjourney.com/hc/en-us/articles/32859204029709-Parameter-List).

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
| `stylize` | `--s` | 0–1000 | Strength of Midjourney's house aesthetic. Lower lets the `sref` dominate. |
| `style_raw` | `--style raw` | on/off (default on) | Suppresses Midjourney's default opinion injection. |
| `oref` | `--oref` | single-image URL | Omni-reference: v7's identity lock — "same subject, new pose/angle". |
| `ow` | `--ow` | 0–1000 (default 100) | Omni-weight: how tightly to hold the `oref` identity. |
| `negatives` | `--no` | list of phrases | Things to suppress (text, watermarks, extra limbs). Emitted as the final flag. |
| `image_prompts` | (leading URLs) | list of image URLs | Reference images Midjourney blends in; emitted before the subject. |
| `image_weight` | `--iw` | 0–3 | How strongly the image prompts pull. Meaningless without `image_prompts`. |
| `tile` | `--tile` | on/off | Seamless, repeating output. |
| `chaos` | `--chaos` | 0–100 | Variety across the four grid candidates. |
| `weird` | `--weird` | 0–3000 | Offbeat / unconventional aesthetics. |
| `stop` | `--stop` | 10–100 | Halt the render early for a rougher draft. |
| `quality` | `--q` | 1, 2, or 4 | GPU-cost lever on the initial grid (no `--q 3` in v7). |
| `seed` | `--seed` | 0–4294967295 | Near-reproducibility within a fixed model + params. |

`--v 7` is always emitted; it is not a parameter you set.

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
| `animate_high` / `animate_low` | Image → video (high / low motion) | an animated WebP (`image/webp`, ~125 frames), not an mp4 |
| `favorite` | Bookmark the image in Midjourney | no artifact (no-op for the pipeline) |

> Known v0.1 limit: a derived result that is itself a grid (vary/zoom/pan) is
> recorded in `derived` but not re-tracked as a new job, so you can't then
> `mj_action` on its quadrants.

---

## Not wired yet (real v7 features cascade-img doesn't expose at v0.1)

These are current v7 capabilities, intentionally out of scope for v0.1 — listed
so the boundary is explicit rather than implied:

- **`--sw` (style-reference weight, 0–1000).** You can set `--sref` but not yet
  how strongly it pulls.
- **Draft Mode (`--draft`).** Faster, cheaper draft renders.
- **GPU mode** (fast / relax / turbo) and **Stealth** (`--stealth`, private
  renders). cascade-img uses the account's default mode.
- **`--repeat`** (fire the same prompt N times in one call).
- **Native `/imagine` video parameters** (video resolution / batch size).
  Animation is available instead via the `animate_*` action above.
- **Character Reference (`--cref` / `--cw`).** Superseded in v7 by Omni Reference
  (`--oref` / `--ow`), which **is** supported.

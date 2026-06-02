# Wave F — live button capture (2026-06-02)

Captured from a real Midjourney v7 response (upscaled single image) via
`tools/mj_capture_buttons.py` against the operator's account. This is the
authoritative bridge mapping for Wave F — endpoints/matchers are written
against these real `custom_id`s, read off the live message at press time
(never hardcoded; the uuid varies per job).

## Action buttons on the upscaled image

| Action | Discord label | custom_id pattern | Tier |
|---|---|---|---|
| upscale_subtle | Upscale (Subtle) | `MJ::JOB::upsample_v7_2x_subtle::1::{uuid}::SOLO` | press |
| upscale_creative | Upscale (Creative) | `MJ::JOB::upsample_v7_2x_creative::1::{uuid}::SOLO` | press |
| vary_subtle | Vary (Subtle) | `MJ::JOB::low_variation::1::{uuid}::SOLO` | press → new grid |
| vary_strong | Vary (Strong) | `MJ::JOB::high_variation::1::{uuid}::SOLO` | press → new grid |
| vary_region | Vary (Region) | `MJ::Inpaint::1::{uuid}::SOLO` | modal + mask — DEFER |
| zoom_out_2x | Zoom Out 2x | `MJ::Outpaint::50::1::{uuid}::SOLO` | press → new grid |
| zoom_out_1_5x | Zoom Out 1.5x | `MJ::Outpaint::75::1::{uuid}::SOLO` | press → new grid |
| custom_zoom | Custom Zoom | `MJ::CustomZoom::{uuid}` | modal — DEFER (needs modal-submit primitive) |
| pan_left/right/up/down | (emoji only) | `MJ::JOB::pan_{dir}::1::{uuid}::SOLO` | press → new grid |
| animate_high | Animate (High motion) | `MJ::JOB::animate_high::1::{uuid}::SOLO` | press → video |
| animate_low | Animate (Low motion) | `MJ::JOB::animate_low::1::{uuid}::SOLO` | press → video |
| favorite | (❤ emoji only) | `MJ::BOOKMARK::{uuid}` | press (no result message) |
| web | Web | (link `url`, no custom_id) | link-only — expose URL |

## What this settles

- **Submit side is a single primitive.** Every actionable button is a component
  press the existing `_press_button` already does. The bridge fetches the
  target message's live components, finds the button whose `custom_id` matches
  the requested action's pattern, and presses it. No hardcoded ids.
- **Custom Zoom and Vary (Region) are the only modal/mask cases** — deferred;
  they need a modal-submit primitive the bridge lacks.

## Receive-side capture (2026-06-02, live via tools/mj_capture_results.py)

Pressed Vary (Strong) then Animate (High) on a real upscaled image:

**vary_strong → new 2x2 grid (CONFIRMED).** A new message with a `.webp` grid +
upsample buttons, carrying a NEW job uuid (`9fb1bd30-…`) but **re-echoing the
parent prompt + the same `--no cscidnocollide` token**. The existing
`_match_grid` keys on that token, so it would mis-route the result to the parent
— confirming the spec. The result content carries a distinguishing marker:
`… - Variations (Strong) by <@…> … (fast)`. Receive-side matcher therefore
routes a derived grid by: token present (lineage) + a NEW uuid (not the parent's)
+ the action marker in content. vary_subtle / zoom_out / pan_* echo the same
shape with their own markers ("Variations (Subtle)", "Zoom Out", "Pan").

**animate_high → video result, lands in Discord (~60s). [CORRECTED]** An earlier
capture wrongly concluded "web-only"; that was a bug in the harness (a content
gate on the parent token + too-short timeout), not MJ's behavior. Re-captured
with no content gate: pressing Animate fires a video job MJ rewrites to
`--motion high --video 1 --aspect <ar>` with a NEW job uuid (e.g. `aeebebb3-…`).
Progress streams as `.jpeg` step-frames; the result message lands within ~60s
with the video (plus its own action buttons and an "Open on website for full
quality" link). KEY routing wrinkle: the result content does NOT echo the parent
`--no cscidnocollide` token (`has_needle=false`), so it can't be routed by the
parent token the way a derived grid is. Route an animate result by the rewritten
`--motion/--video` content marker + a video/animated-webp attachment + recency
relative to the press; link it to the parent via the press the bridge just made.

## Wave F implementation plan (now fully data-grounded)

- `Job` gains `parent_job_id`; the bridge tracks the upscaled image's
  `message_id` (the SOLO action buttons live there).
- A press endpoint + MCP tool per action presses the live `custom_id` via the
  existing `_press_button` (custom_ids read off the live message, never hardcoded).
- vary/zoom/pan create a CHILD job (parent_job_id set) awaiting a new grid; a new
  match path routes a derived grid (token + NEW uuid + action marker) to it.
- animate: the press fires a video job that DOES return to Discord (~60s) with a
  rewritten `--motion/--video` prompt + new uuid and NO parent token. Route the
  result by the `--video` content marker + video attachment + recency; expose the
  video attachment and the job URL. (Not submit-only — corrected.)
- favorite is a fire-and-forget toggle (no result message).
- Custom Zoom / Vary (Region) stay deferred (modal / mask-upload primitives).

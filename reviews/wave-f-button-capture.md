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

## Still to capture (receive side, next live step)

How MJ echoes each result, so the matcher routes it to the child job:
- vary_*/zoom_*/pan_* → a **new 2x2 grid** (new message; re-echoes parent prompt
  + token, so a new uuid/nonce match path is needed, not the parent token).
- animate_high/low → a **video** (.mp4 attachment, or web-only at launch — must
  confirm how/whether it lands on Discord and the download/content-type path).
- favorite → likely no result message (state toggle only).

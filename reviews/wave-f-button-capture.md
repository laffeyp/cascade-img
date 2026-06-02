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

**animate_high → NO Discord echo within 340s (web-only).** The press fires the
job (visible on midjourney.com via the job URL) but the video does not land as a
Discord attachment in a reasonable window. SDD substrate-gap conclusion: Animate
is **submit-only** over the bridge — press + surface the job URL; do NOT
implement a Discord-side video matcher (don't fake-emit a result the substrate
doesn't deliver). Revisit if MJ starts posting the video to the channel.

## Wave F implementation plan (now fully data-grounded)

- `Job` gains `parent_job_id`; the bridge tracks the upscaled image's
  `message_id` (the SOLO action buttons live there).
- A press endpoint + MCP tool per action presses the live `custom_id` via the
  existing `_press_button` (custom_ids read off the live message, never hardcoded).
- vary/zoom/pan create a CHILD job (parent_job_id set) awaiting a new grid; a new
  match path routes a derived grid (token + NEW uuid + action marker) to it.
- animate is submit-only: press + return the job URL; no result matcher.
- favorite is a fire-and-forget toggle (no result message).
- Custom Zoom / Vary (Region) stay deferred (modal / mask-upload primitives).

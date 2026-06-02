# Wave F — Receive-Side Capture (authoritative observation record)

**Captured:** 2026-06-02, live Midjourney v7 account, via `cascade-mj-bridge` with
`CASCADE_CAPTURE_RAW` instrumentation. **Method:** every message authored by the MJ
bot (`936929561302675456`) in the watched channel (`1502243953687265485`) was appended
verbatim (structure only, no interpretation) to `/tmp/cascade-live-out/raw-capture.jsonl`
(copied to `reviews/wave-f-raw-capture.jsonl`, 86 lines). This document quotes the data;
**nothing here is guessed**. Where MJ did not emit something, that absence is stated.

This is the file the receive-side matchers will be built from. Fidelity over interpretation.

---

## 0. The run that produced the data

- Parent job: `imagine(asset_id="livebird", upscale="1")`, job_id `049c3cb9c29049af9af873951c46f30c`.
- Composed prompt: `a small bird pixel-art sprite, single centered character, clean transparent background --ar 1:1 --v 7 --style raw --no background scenery, drop shadow, frame`
- Per-job routing token woven in by the bridge: `cscidnocollide781b1185` (appears as a `--no` clause member in MJ's echoes).
- Grid message id: `1511317204245680259`. **SOLO upscaled-image message id: `1511317210822611026`** (this is the message that carries the vary/zoom/pan/animate/favorite buttons; it is the `upscale_message_id` the bridge records, and the parent that every derived result references).
- Grid SOLO uuid (U1): `bb5d727b-4df5-4c9b-be01-96d2f526c49e`.

Then, via the `mj_action` MCP tool, one action was pressed from each family and the
new capture lines were read after each.

### IMPORTANT caveat about the `event` field in the authoritative jsonl

The authoritative 86-line capture was taken with the first revision of the hook, which
tried to ride the `event="edit"` tag on the `discord.Message` object. `discord.Message`
is `__slots__`-based (40 slots, no `__dict__`), so that attribute set raised
`AttributeError` and was swallowed by the hook's `suppress`. **Result: every line in
`wave-f-raw-capture.jsonl` is tagged `"event": "message"`, even though many are in-place
MJ progress edits.** The capture is otherwise complete — every edit pass WAS captured —
you simply cannot distinguish create from edit by the `event` field in this file.

This was diagnosed and fixed in `bridge.py`: `_ingest_message(message, event="message")`
now takes the event as a call argument and `on_message_edit` passes `"edit"`. A second
short live run (`/tmp/cascade-live-out/raw-capture-verify.jsonl`) confirms the fix:
`{"message": 2, "edit": 6}`. So MJ **does** drive progress via message edits, and
the corrected hook now records that distinction. (You can also infer edits in the
authoritative file: a message id appearing on multiple lines was edited in place — e.g.
the SOLO message `1511317210822611026` appears 6 times.)

---

## 1. The SOLO upscaled-image message — the button source (raw-capture line 47)

This is the message `mj_action` presses. Its 16 components, verbatim, with the live
custom_ids. Note every `MJ::JOB::*` id embeds the SOLO uuid `bb5d727b-...` and ends `::SOLO`;
`MJ::Inpaint`, `MJ::Outpaint::50/75`, `MJ::CustomZoom`, `MJ::BOOKMARK` are distinct shapes.

```json
{
  "event": "message",
  "id": 1511317210822611026,
  "channel_id": 1502243953687265485,
  "author_id": 936929561302675456,
  "created_at": "2026-06-02T10:35:01.976000+00:00",
  "edited_at": "2026-06-02T10:38:07.250860+00:00",
  "content": "**a small bird pixel-art sprite, single centered character, clean transparent background --ar 1:1 --v 7.0 --no background scenery, drop shadow, frame, cscidnocollide781b1185 --raw** - Image #1 <@1502242966100639815>",
  "message_reference": 1511317204245680259,
  "attachments": [
    {
      "filename": "u2233346927_a_small_bird_pixel-art_sprite_single_centered_chara_bb5d727b-4df5-4c9b-be01-96d2f526c49e.png",
      "content_type": "image/png", "size": 389450, "width": 1024, "height": 1024, "duration": null
    }
  ]
}
```

Button inventory (custom_id | label | style):

```
MJ::JOB::upsample_v7_2x_subtle::1::bb5d727b-...::SOLO   | Upscale (Subtle)        | 2
MJ::JOB::upsample_v7_2x_creative::1::bb5d727b-...::SOLO | Upscale (Creative)      | 2
MJ::JOB::low_variation::1::bb5d727b-...::SOLO           | Vary (Subtle)           | 2
MJ::JOB::high_variation::1::bb5d727b-...::SOLO          | Vary (Strong)           | 1
MJ::Inpaint::1::bb5d727b-...::SOLO                      | Vary (Region)           | 2
MJ::Outpaint::50::1::bb5d727b-...::SOLO                 | Zoom Out 2x             | 1
MJ::Outpaint::75::1::bb5d727b-...::SOLO                 | Zoom Out 1.5x           | 2
MJ::CustomZoom::bb5d727b-...                            | Custom Zoom             | 2
MJ::JOB::pan_left::1::bb5d727b-...::SOLO                | (none)                  | 2
MJ::JOB::pan_right::1::bb5d727b-...::SOLO               | (none)                  | 2
MJ::JOB::pan_up::1::bb5d727b-...::SOLO                  | (none)                  | 2
MJ::JOB::pan_down::1::bb5d727b-...::SOLO                | (none)                  | 2
MJ::JOB::animate_high::1::bb5d727b-...::SOLO            | Animate (High motion)   | 2
MJ::JOB::animate_low::1::bb5d727b-...::SOLO             | Animate (Low motion)    | 2
MJ::BOOKMARK::bb5d727b-...                              | (none)                  | 2
(custom_id null)                                       | Web  (style 5 link btn) | 5
```

Every marker in the bridge's `_ACTION_MARKERS` dict matches a real button here. The
mapping is correct against the live v7 SOLO message as of 2026-06-02.

---

## 2. Per-family derived results (verbatim)

For each family below: what `mj_action` pressed, the **new MJ job uuid** minted, the
final-result attachment, and the parent-link answer. All six presses returned the bridge
envelope `{ok:true, result:{custom_id, message_id:1511317210822611026, ...}}`.

### vary_strong  (pressed `MJ::JOB::high_variation::1::bb5d727b-...::SOLO`)
Final result: **raw-capture line 37**, message id `1511317624292769933`.

```json
{
  "id": 1511317624292769933,
  "content": "**a small bird pixel-art sprite, single centered character, clean transparent background --ar 1:1 --v 7.0 --no background scenery, drop shadow, frame, cscidnocollide781b1185 --raw** - Variations (Strong) by <@1502242966100639815> [(Open on website for full quality)](<https://midjourney.com/jobs/9a5aa072-26f3-4902-a2e2-f76f2db12270>) (fast)",
  "message_reference": 1511317210822611026,
  "attachments": [{
    "filename": "u2233346927_..._9a5aa072-26f3-4902-a2e2-f76f2db12270.webp",
    "content_type": "image/webp", "size": 295714, "width": 2048, "height": 2048, "duration": null
  }]
}
```
- New MJ job uuid: `9a5aa072-26f3-4902-a2e2-f76f2db12270`.
- Result is a fresh **2x2 grid** (its buttons are `U1..U4`, `V1..V4`, `reroll`).
- Prompt text: MJ re-echoes the SOLO prompt **verbatim, including `cscidnocollide781b1185`**, and prepends `- Variations (Strong) by`.

### zoom_out_2x  (pressed `MJ::Outpaint::50::1::bb5d727b-...::SOLO`)
Final result: **raw-capture line 53**, message id `1511318098567762011`.

```json
{
  "id": 1511318098567762011,
  "content": "**...frame, cscidnocollide781b1185 --raw** - Zoom Out by <@1502242966100639815> [(Open on website for full quality)](<https://midjourney.com/jobs/acdc5004-1a50-41f3-b367-f1d9a87a6558>) (fast)",
  "message_reference": 1511317210822611026,
  "attachments": [{
    "filename": "u2233346927_..._acdc5004-1a50-41f3-b367-f1d9a87a6558.webp",
    "content_type": "image/webp", "size": 143868, "width": 2048, "height": 2048, "duration": null
  }]
}
```
- New MJ job uuid: `acdc5004-1a50-41f3-b367-f1d9a87a6558`.
- Result is a fresh 2x2 grid (`U1..U4`, `V1..V4`).
- Prompt text: SOLO prompt verbatim incl. token; suffix `- Zoom Out by`. MJ does NOT add a visible `--zoom`/`--out` flag to the echoed content (the action is encoded in the button, not the prompt text).

### pan_right  (pressed `MJ::JOB::pan_right::1::bb5d727b-...::SOLO`)
Final result: **raw-capture line 61**, message id `1511318524574957568`.

```json
{
  "id": 1511318524574957568,
  "content": "**a small bird pixel-art sprite, ... --v 7.0 --no background scenery, drop shadow, frame, cscidnocollide781b1185 --raw --ar 3:2** - Pan Right by <@1502242966100639815> [(Open on website for full quality)](<https://midjourney.com/jobs/0c1e00fa-a96d-4df7-99b3-65eb17bb60c6>) (fast)",
  "message_reference": 1511317210822611026,
  "attachments": [{
    "filename": "u2233346927_..._0c1e00fa-a96d-4df7-99b3-65eb17bb60c6.webp",
    "content_type": "image/webp", "size": 383346, "width": 2688, "height": 1792, "duration": null
  }]
}
```
- New MJ job uuid: `0c1e00fa-a96d-4df7-99b3-65eb17bb60c6`.
- **Prompt text IS rewritten by MJ for pan:** the echoed prompt drops the original `--ar 1:1` and appends **`--ar 3:2`** (the panned canvas is wider). Result dims `2688x1792` (a 3:2 ratio) confirm the widened canvas. Suffix `- Pan Right by`.
- Result is a fresh 2x2 grid (`U1..U4`, `V1..V4`).

### upscale_creative  (pressed `MJ::JOB::upsample_v7_2x_creative::1::bb5d727b-...::SOLO`)
Final result: **raw-capture line 71**, message id `1511319011097575516`.

```json
{
  "id": 1511319011097575516,
  "content": "**...frame, cscidnocollide781b1185 --raw** - Upscaled by <@1502242966100639815> (fast)",
  "message_reference": 1511317210822611026,
  "attachments": [{
    "filename": "u2233346927_..._7758c7cb-d151-48de-8c0c-90399e7e1939.png",
    "content_type": "image/png", "size": 633555, "width": 2048, "height": 2048, "duration": null
  }]
}
```
- New MJ job uuid: `7758c7cb-d151-48de-8c0c-90399e7e1939`.
- Result is a single upscaled **PNG** (2048x2048), NOT a grid. Its buttons are themselves a SOLO-style set: `Redo Upscale (Subtle/Creative)`, `Vary (Subtle/Strong)`, `Animate (High/Low)`, `BOOKMARK`, `Web` — i.e. this derived result is itself actionable.
- No `(Open on website...)` link in this content; suffix `- Upscaled by`.
- Prompt text: SOLO prompt verbatim incl. token.

### animate_high  (pressed `MJ::JOB::animate_high::1::bb5d727b-...::SOLO`)
Final result: **raw-capture line 85**, message id `1511319451277201564`. **(This is the video case.)**

```json
{
  "id": 1511319451277201564,
  "content": "**a small bird pixel-art sprite, single centered character, clean transparent background --raw --motion high --video 1 --aspect 1:1** - <@1502242966100639815> [(Open on website for full quality)](<https://midjourney.com/jobs/9bdd338a-3876-4b4b-b175-af661e8a8cab>) (fast)",
  "message_reference": 1511317210822611026,
  "attachments": [{
    "filename": "u2233346927_..._9bdd338a-3876-4b4b-b175-af661e8a8cab.webp",
    "content_type": "image/webp", "size": 2496346, "width": 624, "height": 624, "duration": null
  }],
  "components": [ U1..U4 = "MJ::JOB::video_virtual_upscale::N::9bdd338a-...", reroll, link ]
}
```
- New MJ job uuid: `9bdd338a-3876-4b4b-b175-af661e8a8cab`.
- **The video attachment is an ANIMATED WEBP, not an mp4.** Downloaded the full 2,496,346 bytes via `requests` (HTTP 200, `Content-Type: image/webp`); saved to `/tmp/cascade-live-out/animate_result.webp`. PIL confirms: `format=WEBP, mode=RGBA, size=624x624, is_animated=True, n_frames=125, loop=0` (infinite). The Discord attachment `duration` field is **null** (Discord only populates `duration` for voice-message attachments; it does not carry video length for MJ animations).
- **Prompt text IS rewritten by MJ for animate:** the echoed prompt becomes `--raw --motion high --video 1 --aspect 1:1` and **drops the `--no cscidnocollide...` clause entirely**. So the parent routing token does NOT appear in the animate result content.
- The animate output is a 2x2 motion grid (its `U1..U4` are `video_virtual_upscale` buttons, one per cell). Frames rendered visually show the grey/red-crested pixel bird animating (head turns, wing/tail raises).
- **Latency:** press at epoch 1780396983 (10:42:23 UTC); final webp message created_at 10:43:56.142 UTC = **~53.1 s** press-to-result. Progress frames (256x256 `image/jpeg`, `..._N_step_M.jpeg`) streamed in the intervening edits.

### favorite  (pressed `MJ::BOOKMARK::bb5d727b-...`)
Final result: **raw-capture line 86**, message id `1511319783969263847`.

```json
{
  "id": 1511319783969263847,
  "content": "You have successfully rated [this job](https://discord.com/channels/1502243952852729909/1502243953687265485/1511317210822611026) with 😍",
  "message_reference": 1511317210822611026,
  "attachments": [],
  "components": []
}
```
- **favorite does NOT produce a new image/job.** It posts a short confirmation message:
  "You have successfully rated [this job](...) with 😍". No attachment, no components, no
  new MJ job uuid. The `[this job]` link embeds the SOLO message URL
  (`.../channels/<guild>/<channel>/1511317210822611026`), and `message_reference` also
  equals the SOLO id. (Empirically this run produced a NEW confirmation message rather
  than a silent toggle; recorded as observed.)

---

## 3. The four questions, answered FROM THE DATA

### (a) Does the derived result content contain the parent routing token `cscidnocollide781b1185`?

| family            | token echoed in content? |
|-------------------|--------------------------|
| vary_strong       | **YES** — `...frame, cscidnocollide781b1185 --raw...` |
| zoom_out_2x       | **YES** |
| pan_right         | **YES** |
| upscale_creative  | **YES** |
| animate_high      | **NO** — MJ rewrites the prompt to `--raw --motion high --video 1 --aspect 1:1` and drops the `--no` clause |
| favorite          | **NO** — confirmation text only, no prompt echo |

This is the **opposite** of the prior hypothesis ("likely NOT"). For vary/zoom/pan/upscale,
MJ re-echoes the parent SOLO prompt verbatim, so the parent token IS present and could route
those derived results back to the originating asset by substring. For animate and favorite it
is NOT present.

### (b) Does it carry a NEW MJ job uuid in its buttons? Does MJ rewrite the prompt?

Yes — each non-favorite derived result mints a **new** uuid and embeds it in its buttons
and in the `(Open on website for full quality)` `midjourney.com/jobs/<uuid>` link and in
the attachment filename:

| family            | new MJ job uuid                          | prompt rewrite |
|-------------------|------------------------------------------|----------------|
| vary_strong       | `9a5aa072-26f3-4902-a2e2-f76f2db12270`   | none (verbatim) + `- Variations (Strong) by` |
| zoom_out_2x       | `acdc5004-1a50-41f3-b367-f1d9a87a6558`   | none in text + `- Zoom Out by` |
| pan_right         | `0c1e00fa-a96d-4df7-99b3-65eb17bb60c6`   | **`--ar 1:1` → `--ar 3:2`** + `- Pan Right by` |
| upscale_creative  | `7758c7cb-d151-48de-8c0c-90399e7e1939`   | none + `- Upscaled by` |
| animate_high      | `9bdd338a-3876-4b4b-b175-af661e8a8cab`   | **full rewrite: `--raw --motion high --video 1 --aspect 1:1`, `--no` dropped** |
| favorite          | (none — no job)                          | (no echo) |

### (c) animate_high specifically — what IS the video?

- Attachment `content_type`: **`image/webp`** (NOT `video/mp4`).
- Real downloaded byte size: **2,496,346 bytes** (matches the record `size` and the
  `Content-Length` header; download via `requests` succeeded HTTP 200; urllib failed 403
  because it mishandled the signed CDN query string + UA — use `requests` like the bridge's
  `_download_to`).
- Dimensions: **624x624**. `duration` attachment field: **null**.
- It is an **animated WebP, 125 frames, infinite loop** (PIL `is_animated=True, n_frames=125, loop=0`).
- Latency: **~53 s** from press to final webp message.
- Frame description (vision): the upscaled grey pixel-bird with red crest, in motion — a
  2x2 video grid where panels show head-turn / wing-and-tail-raise variations.
- The progress edits carried intermediate `256x256 image/jpeg` step-frames
  (`<uuid>_<cell>_step_<n>.jpeg`).

### (d) Is there ANY stable field that routes a derived result to its parent?

**YES — observed in every one of the six results:** `message_reference` (i.e.
`discord.Message.reference.message_id`) **equals the SOLO message id `1511317210822611026`**
for all six families, including animate and favorite (which do NOT echo the token).

```
vary_strong        message_reference = 1511317210822611026  == SOLO   ✓
zoom_out_2x        message_reference = 1511317210822611026  == SOLO   ✓
pan_right          message_reference = 1511317210822611026  == SOLO   ✓
upscale_creative   message_reference = 1511317210822611026  == SOLO   ✓
animate_high       message_reference = 1511317210822611026  == SOLO   ✓
favorite           message_reference = 1511317210822611026  == SOLO   ✓
```

So there are TWO observed routing signals, with different coverage:
1. **`message_reference.message_id == upscale_message_id` (the SOLO id)** — present on ALL
   six families. This is the strongest, most uniform parent link. The bridge already
   records `upscale_message_id`; a matcher can key on `message.reference.message_id`.
2. **Parent routing token `cscidnocollide781b1185` in content** — present on
   vary/zoom/pan/upscale only; absent on animate/favorite. Useful as a secondary signal
   for the prompt-echoing families, and it carries through to the asset (not just the SOLO
   message), which `message_reference` does not.

(No interaction-metadata field was present in the captured structure; the bridge does not
surface Discord interaction-response metadata in `_ingest_message`. Only the two signals
above were observed. Nothing else is proposed.)

---

## 4. Cross-talk warning for the matchers (observed, not hypothetical)

The watched channel is shared. During this capture, a DIFFERENT job — prompt
`a classic 2000s mobile game scene come alive as 3D sprites` (its own animate, uuids
`564950e3-...`, `df062413-...`) — interleaved into the same window (raw-capture lines
26-27, 31-32, 34, 38-45). Its 12.4 MB animate webp landed at line 45, INSIDE my
vary_strong window. **A temporal/adjacency matcher would mis-route it.** The
`message_reference == SOLO id` signal and the `cscidnocollide<token>` signal both correctly
exclude this foreign job (its ref points at its own SOLO/grid `1511317460668780624`, and it
carries no `cscidnocollide781b1185`). This is concrete evidence that the matchers MUST key
on a parent field, not on recency.

---

## 5. Attachment content_type census across the whole capture

```
image/webp : 33   (grid previews, vary/zoom/pan finals, animate finals)
image/jpeg : 48   (animate progress step-frames, 256x256)
image/png  :  9   (SOLO upscale, upscale_creative final, grids)
video/*    :  0   (NONE — animate is delivered as animated webp)
```

No `video/*` content_type was ever observed. The "video" product is an animated `image/webp`.

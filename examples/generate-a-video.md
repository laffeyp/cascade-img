# Generate a video

Native Midjourney image→video: take a starting image, animate it into a ~5s
clip, sample it to inspect it, then upscale and extend. Swap the placeholder
image URL and subject for your own.

A video job differs from an image job in three ways worth knowing up front:

- The result is **one animated webp**, not a grid — there is no U1–U4 stage.
- Videos **bind FIFO** (a video prompt can't carry the `--no` routing token), so
  the bridge accepts **one unbound video at a time**: a `VIDEO_IN_FLIGHT` (409)
  means a prior video is still awaiting its first Midjourney ack — poll `wait`
  then submit the next, don't re-roll.
- To **extend** a clip you must **upscale a slot first** (`video_upscale`),
  then `extend_*` keys off that SOLO's own slot.

## Steps

1. **Check the bridge.** `bridge_health()`. If `discord_ready` is false, wait a
   few seconds and retry; if it stays false, stop and tell the human.

2. **Generate the clip.** `generate_video(...)` composes the video prompt and
   fires it in one call:
   - `image_url`: the starting frame (required) — a URL to the image you want to
     animate (e.g. an upscale you promoted from an earlier image roll).
   - `asset_id`: e.g. `"mountain-flythrough"`.
   - `text` (optional): what should happen, e.g. `"slow camera push toward the
     peak, drifting clouds"`.
   - `motion` (optional): `"low"` (subtle) or `"high"` (energetic).
   - `loop=True` for a seamless loop (reuses the start frame as the end frame),
     **or** `end_frame=<url>` for a different end frame — the two are mutually
     exclusive.
   - `batch_size` (optional): `1`, `2`, or `4` clips.

   To build the prompt without firing it, use `compose_video(...)` with the same
   params and inspect the string first.

3. **Wait.** `wait(job_id, timeout=600)` — video renders are slower than images.
   On `done` you get the animated-webp path. A timeout is not a failure — poll
   `wait`/`status` again rather than re-firing (re-firing double-bills).

4. **Inspect.** `video_filmstrip(src=<video_path>, dest="mountain-strip.png",
   frames=5)` samples keyframes into one still you can open and read with vision.
   For a `loop=True` clip, also run `loop_seam_delta(src=<video_path>)` — it
   scores how cleanly the last frame meets the first; a high delta means a
   visible seam (re-roll or drop `loop`).

5. **Upscale a slot (optional).** To get a higher-resolution SOLO clip, or as the
   prerequisite for extending: `mj_action(job_id, action="video_upscale",
   slot=1)`. When its clip lands, the bridge emits `MJ_ACTION_SURFACE_REGISTERED`
   recording that slot as an extendable surface.

6. **Extend (optional).** `mj_action(job_id, action="extend_high", slot=1)` (or
   `"extend_low"`) on the **same slot** you upscaled adds ~5s more. Calling
   `extend_*` before `video_upscale` returns `NO_UPSCALED_IMAGE` telling you to
   upscale first. There is no exposed `video_reroll` — to re-roll, call
   `generate_video` again.

7. **Log.** `log_append(asset_id="mountain-flythrough", prompt=<the composed
   video prompt>, job_id=<job_id>, outputs={"video_path": "..."},
   agent_decision="promote", agent_reason="<one line: why this clip was
   acceptable>")`.

## Done

The asset has a `promote` record in the log pointing at the final clip, or — if
nothing acceptable came out after a couple of re-rolls — an `escalate` record
explaining what you tried.

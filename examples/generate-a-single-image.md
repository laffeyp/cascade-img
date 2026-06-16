# Generate a single image

The smallest end-to-end loop: compose → imagine → wait → curate → log. Swap the
placeholder subject for your own.

## Steps

1. **Check the bridge.** `bridge_health()`. If `discord_ready` is false, wait a
   few seconds and retry; if it stays false, stop and tell the human.

2. **Compose the prompt.** `compose_prompt(...)`:
   - `subject`: a plain description of what you want, e.g.
     `"a flat-design icon of a mountain, centered, simple shapes"`.
   - `aspect_ratio`: e.g. `"1:1"`.
   - `version`: defaults to `"8.1"` (Midjourney's current model). Pass `"7"`
     only when you need an Omni Reference identity lock or `--q` — both are
     V7-only and the call raises if you set them on the V8.1 default.
   - Optional style controls, only if the human gave you any: `moodboard`,
     `sref` (a reference-image URL), `oref` + `ow` (identity lock — **requires
     `version="7"`**).

3. **Generate.** `imagine(prompt, asset_id="mountain-icon", upscale="1")`.
   Use `upscale="all"` instead if you want four upscaled candidates to choose
   between rather than one.

4. **Wait.** `wait(job_id, timeout=360)` for a single upscale (use `180` for a
   grid-only roll, `600` for `upscale="all"`). On `done` you get `image_path`
   and `grid_path`. A timeout is not a failure — poll `wait`/`status` again
   rather than re-firing `imagine` (re-firing double-bills the render).

5. **Inspect.** Open `image_path` and check it matches the request.

6. **Curate (optional).** For a transparent cut-out:
   `alpha_key(src=image_path, dest="mountain-icon-keyed.png")`, then
   `promote(src="mountain-icon-keyed.png", dest="out/mountain-icon.png")`.

7. **Log.** `log_append(asset_id="mountain-icon", prompt=<the composed prompt>,
   job_id=<job_id>, outputs={"image_path": "..."}, agent_decision="promote",
   agent_reason="<one line: why this result was acceptable>")`.

## Done

The asset has a `promote` record in the log, or — if nothing acceptable came out
after a couple of re-rolls — an `escalate` record explaining what you tried.

# Generate a batch of related images

The single-image loop, repeated over a list whose items share one visual style.
The pattern: read the log first so you never redo finished work; generate; pick
the best candidate; curate; log.

## Pre-flight (once)

1. `bridge_health()` — confirm `discord_ready` is true.
2. Settle the shared style with the human: a `moodboard` code and/or an `sref`
   reference-image URL every item should follow, plus the `aspect_ratio`.

## Per item

For each `asset_id` in the list:

1. **Read the log.** `read_prompt_log(n=5)` — if this asset already has a
   `promote` record, skip it; don't redo finished work.

2. **Compose.** `compose_prompt(subject=<this item's description>,
   moodboard=<shared>, sref=<shared>, aspect_ratio=<shared>)`. Keep the shared
   style fixed; vary only the subject.

3. **Generate four candidates.** `imagine(prompt, asset_id, upscale="all")` so
   you have four upscales to choose among, not a single roll.

4. **Wait.** `wait(job_id, timeout=600)` → `upscale_paths` (a dict keyed 1–4).

5. **Pick.** Open each of the four and choose the one that best matches the
   request and the shared style. If none are acceptable, regenerate with a tighter
   subject description; after ~3 misses, escalate to the human.

6. **Curate.** Crop the winning quadrant out of the grid and promote it:
   ```
   crop_grid(src=grid_path, quadrant=<winning number 1-4>, dest="staging/<asset_id>.png")
   promote(src="staging/<asset_id>.png", dest="out/<asset_id>.png")
   ```
   Add `alpha_key(src=..., dest=...)` between those two if you need a
   transparent background.

7. **Log.** `log_append(asset_id, prompt=<composed prompt>, job_id, upscale="all",
   outputs={...}, agent_decision="promote", agent_reason="<why this one won>")`.

## Done

Every `asset_id` has either a `promote` record or an `escalate` record. Report a
short summary to the human: how many promoted, how many escalated, and a
one-line reason for each escalation.

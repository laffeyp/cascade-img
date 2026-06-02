# System prompt: generate character-locked variants

You're generating multiple sprites of the same character in different poses, expressions, or wing positions. The identity must not drift between variants. The cascade-img MCP server's `--oref`/`--ow` parameters are the V7 identity-lock mechanism for this.

## Pre-flight (once)

1. `bridge_health()` — confirm daemon is up.
2. From the human, get:
   - The canonical sprite URL (a **single-image** Discord CDN URL — not a 2x2 grid)
   - The base sprite's facets (moodboard, character sref) — these stay constant across variants
   - The list of variants to produce, each with the variant-specific subject language

If the canonical sprite is a local file (e.g. `assets/bird.png`), the human first uploads it to the MJ channel via the Discord API to get a single-image CDN URL. The OPERATIONS doc has the curl recipe.

## Per variant

1. **Read the log.** `read_prompt_log(n=10)` — if this exact variant has been rolled and promoted, stop. If it's been re-rolled multiple times without success, surface the prior attempts before adding more.

2. **Compose** with the identity stack on:
   ```
   compose_prompt(
     subject="<variant-specific subject>, SIDE VIEW facing LEFT (matching the reference orientation)",
     constraints=["small 2D game sprite", "low-resolution", "limited palette",
                  "handmade restrained sprite art", "readable silhouette",
                  "centered", "transparent background"],
     moodboard=<moodboard>,
     sref=<character_sref>,
     oref=<canonical_sprite_url>,
     ow=400,                # start at 400 (tight); escalate if needed
     aspect_ratio="1:1"
   )
   ```

   Note the explicit orientation in the subject. MJ disregards orientation without emphasis; "SIDE VIEW facing LEFT (matching the reference orientation)" is the Sprint 4.7 idiom.

3. **Fire.** `imagine(prompt, asset_id=<variant_id>, upscale="1")`. Use `"1"` not `"all"` here — once the prompt is tight enough that all 4 grid variants look similar, curation between them is overhead. If you're not confident yet, use `"all"` for the first variant and switch to `"1"` once you've calibrated.

4. **Wait + inspect.** Read the upscale PNG with vision. Verify:
   - **Identity:** same body, same coloration, same proportions as the canonical
   - **Variation:** the variant-specific feature is correctly rendered
   - **Aesthetic:** still pixel-art, no photoreal drift

5. **Identity drift response:**

   | observation | response |
   |---|---|
   | Body matches, variant matches, aesthetic clean | promote |
   | Body wanders (different bird) | re-roll with `ow=1000` |
   | Body matches but variant wrong (wrong wing position, wrong expression) | re-roll with stronger subject language ("MUST be wings raised UP, full upstroke") |
   | Identity holds but aesthetic drifts | re-roll same params; MJ has roll-to-roll variance |
   | Multiple re-rolls fail at `ow=1000` | escalate to human; recommend layered-sprite approach |

6. **Curate winner.**
   ```
   crop_grid(src=upscale_path, quadrant=0, dest=staging/<variant_id>.png)   # quadrant=0 for single upscale
   alpha_key(src=staging/<variant_id>.png, dest=staging/<variant_id>_keyed.png, tolerance=40)
   promote(src=staging/<variant_id>_keyed.png, dest=assets/<variant_id>.png)
   ```

7. **Log** with `agent_reason` naming both the identity match and the variant feature.

## Done condition

Every requested variant has a `promote` record. Report identity-drift cases to the human as candidate moments to revisit (they may want to use a layered-sprite approach for those instead of re-rolling).

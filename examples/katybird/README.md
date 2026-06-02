# examples/katybird/

Artifacts from the Katybird game project — the first consumer of cascade-img and the origin of the Sprint 4.0 / 4.7 production lessons baked into the bridge daemon and the OPERATIONS doc.

This directory is **not** a generic template set. The prompts here describe how one project drove cascade-img for sprite-art generation; they reference Katybird-specific concepts (Katy, region forest_floor, the apology HUD glyphs, the wing-frame Sprint 4.7 work). They are preserved here for two reasons:

1. **Working example.** A consumer reading these can see how an actual project structured its agent prompts against cascade-img's tool surface. The patterns generalize (read the log first, decide on a lever, escalate after N rolls); the specifics don't.
2. **Audit trail.** Per the project's never-delete discipline, restructures land in new locations rather than removing files. `prompts/` at the project root was the original location; these moved here when the package's scope was narrowed to general-purpose tooling.

Consumers building their own asset pipelines should write their own prompts, informed by their project's vocabulary and constraints — not adopt these verbatim.

## Files

- `prompts/generate-sprite-set.md` — Katybird's bulk-asset-generation loop.
- `prompts/generate-character-locked-variants.md` — wing-frame identity-lock work from Sprint 4.7.
- `prompts/generate-region-backdrop.md` — environmental backdrop generation.
- `prompts/refine-existing-asset.md` — re-rolling against a named problem.

If you want to know how cascade-img is meant to be operated, read [`AGENTS.md`](../../AGENTS.md) at the project root, not these.

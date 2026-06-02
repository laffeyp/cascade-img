## What changed

<!-- One or two sentences. One concern per PR. -->

## Checklist

- [ ] `pytest` passes (run from `packages/engine/`)
- [ ] `ruff check .` and `ruff format --check .` are clean
- [ ] If this adds or changes a state transition: new tags added to `vocabulary/versions/0.1.json` (`payload`, `category`, `stratum`, `note`) and `python3 tools/check_vocabulary_parity.py` is clean
- [ ] Vocabulary mirror in sync: `diff vocabulary/0.1.json packages/engine/src/cascade_img/vocabulary/versions/0.1.json` prints nothing
- [ ] New behavior has a test asserting both the function output AND the emitted event sequence
- [ ] Docs updated where relevant (README / ARCHITECTURE / RUNBOOK / AGENTS)
- [ ] Plain technical wording — no invented house phrasing, no new prescriptions
- [ ] No AI-attribution footers in commits or files

## Notes

<!-- Anything a reviewer should know. -->

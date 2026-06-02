# Sprint 002 — sdd-kit-2 alignment + vocabulary lock

---

```yaml
---
id: 002
status: closed
phase: 2
pass_kind: architecture
opened: 2026-06-02
closed: 2026-06-02
---
```

---

## scope

Make cascade-img conform to sdd-kit-2's conventions. Concrete deliverables:

1. Copy `sdd-kit-2/` into the project as a read-only kit reference.
2. Upgrade `cascade_img.instrumentation.sdd` from a minimal `emit/snapshot` module to a kit-conformant `SignalVocabulary` + `SignalEmitter` with validate-at-emit (kit grammar/PRINCIPLES.md commitment 2), `assert_signal` / `assert_no_signal` test primitives, and `format_for_ai()` digest output.
3. Lock the v0.1 vocabulary (`locked: true`, `locked_at: 2026-06-02`).
4. Mirror `signals/0.1.json` at project root (canonical kit location), in addition to the package-data copy at `packages/engine/src/cascade_img/signals/versions/0.1.json`.
5. Add project-level discipline artifacts at project root: `BLACKBOARD.md`, `WORKING_AGREEMENT.md`, `KIT_DIARY.md`, `signals/0.1-rationale.md`.
6. Backfill `sprints/sprint-001-initial-v0.1.0a1-port.md` for audit trail.
7. Author this card (`sprints/sprint-002-kit-alignment.md`).
8. Run the full discipline ladder green.

---

## prerequisites

- Sprint 001 closed with 48/48 tests green.
- Architect has read the kit alignment direction and confirmed the simplest-first path.

---

## context_files

- `Katybird/Factory v0 synthesis/sdd-kit-2/AGENTS.md` (the tool-agnostic working agreement).
- `Katybird/Factory v0 synthesis/sdd-kit-2/grammar/PRINCIPLES.md` (the 11-layer stack + 7 non-negotiables).
- `Katybird/Factory v0 synthesis/sdd-kit-2/grammar/BOOTSTRAP.md` (the 12-step Vocabulary Session — adapted here for retroactive lock).
- `Katybird/Factory v0 synthesis/sdd-kit-2/lib/sdd.py` (the Python reference library).
- `Katybird/Factory v0 synthesis/sdd-kit-2/templates/BLACKBOARD.md`, `WORKING_AGREEMENT.md`, `KIT_DIARY.md`, `SPRINT_CARD.md`, `SIGNAL_REPORT.md`, `VOCABULARY.json`.
- `Katybird/Factory v0 synthesis/sdd-kit-2/foundations/01-signal-driven-development.md`, `02-sdd-practice.md`, `03-sdd-team-model.md`, `04-sdd-claude-design.md`.
- `Katybird/Factory v0 synthesis/sdd-kit-2/TECHNIQUES.md`.
- `cascade-img/packages/engine/src/cascade_img/instrumentation/sdd.py` (existing minimal version).
- `cascade-img/packages/engine/src/cascade_img/signals/versions/0.1.json` (existing vocabulary).
- `cascade-img/packages/engine/tests/test_sdd.py` (existing tests).

---

## signal contract

### Emits

No new vocabulary tags introduced — the alignment upgrade preserves the existing 27-tag vocabulary verbatim. The validate-at-emit upgrade exercises the existing emit callsites against the locked vocabulary; that's the dual-contract grade.

### Invariants

- No existing emit callsite breaks. Validate-at-emit raises only on unknown tags or missing required fields; the existing callsites pass validation.
- The vocabulary's `vocabulary_version` stays `"0.1"`. Lock flips `locked: false → true`; no tag additions, no payload changes.
- No deletions (kit hard rule). The `_source/` reference copies stay. The previous AGENTS.md (consumer-facing operator guide) stays at project root; the kit's tool-agnostic AGENTS.md inside `sdd-kit-2/` is a separate file with a separate audience.
- No force-push.

---

## artifact contract

### Files created

- `sdd-kit-2/` (a directory copy of `Katybird/Factory v0 synthesis/sdd-kit-2/`).
- `signals/0.1.json` (mirror of the package-data copy).
- `signals/0.1-rationale.md`.
- `BLACKBOARD.md` (at project root).
- `WORKING_AGREEMENT.md` (at project root).
- `KIT_DIARY.md` (at project root).
- `sprints/sprint-001-initial-v0.1.0a1-port.md` (backfill).
- `sprints/sprint-002-kit-alignment.md` (this file).
- `packages/engine/tests/test_sdd_vocabulary.py` (11 new tests for the upgraded sdd module).

### Files modified

- `packages/engine/src/cascade_img/instrumentation/sdd.py` (full rewrite: minimal emit → SignalVocabulary + SignalEmitter with validate-at-emit).
- `packages/engine/src/cascade_img/signals/versions/0.1.json` (lock: `locked: true`, `locked_at: "2026-06-02"`, `locked_by`, `prior_version: null`).

### Content assertions

- `signals/0.1.json` at project root parses as JSON and contains 27 tags.
- `sdd-kit-2/` exists and contains `AGENTS.md`, `CLAUDE.md`, `TECHNIQUES.md`, `README.md`, `lib/`, `grammar/`, `templates/`, `foundations/`, `example/`.
- `packages/engine/src/cascade_img/instrumentation/sdd.py` exports `emit`, `snapshot`, `clear`, `flush_to_file`, `format_for_ai`, `assert_signal`, `assert_no_signal`, `SignalVocabulary`, `SignalEmitter`, `Signal`, `vocabulary`, `capture`.
- `BLACKBOARD.md ## Decisions` contains the project-scope decision plus the kit-adoption decision dated 2026-06-02.

### Command exit codes

- `python3 -m build` (from `packages/engine/`) returns 0.
- `pip install dist/cascade_img-0.1.0a1-py3-none-any.whl[dev]` returns 0.
- `python3 tools/check_vocabulary_parity.py` returns 0 with `vocabulary: 27 tags, emit() calls: 36, OK`.
- `pytest tests/` returns 0 with **59 passing** (48 prior + 11 new vocabulary tests).
- `git push origin main` returns 0 (normal fast-forward push, no force).

---

## observation contract

### Expected runtime signals

This sprint is an architecture-band sprint touching instrumentation; the validation lives in the test suite rather than a live capture. The key behaviors graded:

- `emit("NOT_A_REAL_TAG", ...)` raises `ValueError` with message `Unknown signal tag 'NOT_A_REAL_TAG'`.
- `emit("CASCADE_INIT", package_version="x")` (missing `backend`) raises `ValueError` with message `Signal 'CASCADE_INIT' missing required payload fields: ['backend']`.
- `assert_signal("CASCADE_INIT")` returns the matching record after an `emit("CASCADE_INIT", ...)` call.
- `assert_no_signal("JOB_FAILED")` returns None when no JOB_FAILED has been emitted.
- `format_for_ai(context="QA: boot sequence")` returns a string containing `### session`, `### config`, the tag names, and `Vocabulary: 0.1`.

### Expected log substrings (pytest output)

- `[parity] vocabulary: 27 tags`
- `[parity] emit() calls: 36`
- `[parity] OK`
- `59 passed`

---

## done criteria

`sdd-kit-2/` copied in; sdd.py upgraded with validate-at-emit + test primitives + format_for_ai; vocabulary locked at v0.1; project-level discipline artifacts (BLACKBOARD, WORKING_AGREEMENT, KIT_DIARY, rationale, two sprint cards) present at project root; discipline ladder 59/59 green; commit and normal push.

---

## notes

- This sprint adapts kit BOOTSTRAP.md for **retroactive lock** rather than a greenfield Vocabulary Session. The 12-step procedure is collapsed because the vocabulary already exists, locked-by-implication via the 36 emit callsites already in the code. The Layers 0/3/4/5/6/7 expansions are deferred to v0.2 per the rationale doc.
- The kit's `AGENTS.md` inside `sdd-kit-2/` is the tool-agnostic working agreement for **building** cascade-img. The cascade-img project's own `AGENTS.md` at project root is the consumer-facing operator guide for **using** cascade-img. Distinct audiences; both files stay.
- The KIT_DIARY entry for this sprint surfaces two findings the kit maintainer should consider for the next kit version: (1) name the "agent skims kit files as if they were templates" anti-pattern explicitly; (2) provide an explicit retroactive-lock procedure for mid-project kit adoption.

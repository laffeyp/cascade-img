# Sprint 003 — Code review remediation

---

```yaml
---
id: 003
status: closed
phase: 2
pass_kind: functional
opened: 2026-06-02
closed: 2026-06-02
---
```

---

## scope

Act on the external code review delivered 2026-06-02. Land the six in-scope fixes (test JSONL bug, capture docstring, capture test coverage, logging hygiene, dead import, vocabulary-file parity). Defer the four v0.2-scope concurrency/scale items to `BLACKBOARD.md ## Deferred` with concrete remediation pointers. Re-run the discipline ladder green.

---

## prerequisites

- Sprint 002 closed; discipline ladder at 59/59.
- External code review available with line-level findings.

---

## context_files

- The review text itself.
- `packages/engine/tests/test_cli_mj.py` (the JSONL bug).
- `packages/engine/src/cascade_img/instrumentation/sdd.py` (capture docstring).
- `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` (logging.basicConfig at module top).
- `packages/engine/src/cascade_img/mcp_server.py` (dead SSE import).
- `signals/0.1.json` and `packages/engine/src/cascade_img/signals/versions/0.1.json` (two-copy drift surface).

---

## signal contract

### Emits

No new vocabulary tags. All edits operate on existing emit callsites; the validate-at-emit discipline grades the work.

### Invariants

- No emit callsite changes; the 27-tag vocabulary is untouched.
- No deletions (kit hard rule 12). The dead `SseServerTransport` import is removed in-place, not via a deleted file. The corrected docstring and the renamed logging block are in-place edits.
- No force-push.
- Parity tool continues to pass.
- All prior tests continue to pass.

---

## artifact contract

### Files modified

- `packages/engine/tests/test_cli_mj.py` — fix JSONL-as-single-object parse at line 101; assert exactly one record present.
- `packages/engine/src/cascade_img/instrumentation/sdd.py` — correct `capture()` docstring: enter-only clear; exit leaves buffer intact intentionally.
- `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` — remove module-import-time `logging.basicConfig(...)`; move into `main()` guarded by `if not logging.getLogger().handlers:` so embedding callers retain their config.
- `packages/engine/src/cascade_img/mcp_server.py` — remove unused `from mcp.server.sse import SseServerTransport` import.
- `BLACKBOARD.md` — add Sprint 003 entry to `## Built` and Sprint tail; add 4 entries to `## Deferred` for the v0.2-scope smells.
- `KIT_DIARY.md` — add 2026-06-02 Sprint 003 entry naming findings 5–6.

### Files created

- `packages/engine/tests/test_capture_and_vocab_sync.py` — 5 tests:
  - `test_capture_clears_at_enter`
  - `test_capture_leaves_buffer_intact_at_exit`
  - `test_capture_yields_module_emitter`
  - `test_capture_with_context_in_format_for_ai`
  - `test_root_and_package_vocab_files_are_identical`
- `sprints/sprint-003-code-review-remediation.md` — this file.

### Content assertions

- `grep -q "log_path.read_text().splitlines()" packages/engine/tests/test_cli_mj.py` — JSONL is now line-iterated.
- `grep -q "logging.basicConfig" packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` returns matches inside `main()` only (no module-level call).
- `grep -q "SseServerTransport" packages/engine/src/cascade_img/mcp_server.py` returns no matches.
- `signals/0.1.json` byte-equal to `packages/engine/src/cascade_img/signals/versions/0.1.json` (asserted by `test_root_and_package_vocab_files_are_identical`).
- `BLACKBOARD.md ## Deferred` contains four entries naming "JOBS dict grows unbounded", "`/wait` holds a Flask thread", "MidjourneyDiscordBackend.imagine/wait/status/health are async but call requests synchronously", "`_ingest_message` does blocking file I/O".

### Command exit codes

- `python3 -m build` (from `packages/engine/`) returns 0.
- `pip install dist/cascade_img-0.1.0a1-py3-none-any.whl[dev]` returns 0.
- `python3 tools/check_vocabulary_parity.py` returns 0.
- `pytest tests/` returns 0 with **64 passing** (59 prior + 5 new).
- `git push origin main` returns 0 (normal fast-forward).

---

## observation contract

### Expected runtime behavior changes

- Importing `cascade_img.backends.midjourney_discord.bridge` no longer calls `logging.basicConfig`. An embedding caller that has already configured the root logger keeps its config; running `cascade-mj-bridge` as a CLI configures basicConfig if no handlers exist.
- `capture()` behavior is unchanged; only the docstring describes it accurately.
- `mcp_server.py --http <port>` continues to work; the deleted import was dead.
- `test_dry_run_composes_and_logs` now correctly parses JSONL line-by-line; it would no longer regress if the dry-run logged multiple records.

### Expected log substrings (pytest output)

- `64 passed`
- `[parity] vocabulary: 27 tags`
- `[parity] emit() calls: 36`
- `[parity] OK`

---

## done criteria

Six in-scope fixes landed and tested; four v0.2 smells documented in BLACKBOARD ## Deferred with concrete remediation pointers; ladder 64/64 green; commit and normal push.

---

## notes

- The reviewer correctly identified two latent bugs (the JSONL parse + the inaccurate docstring) that the existing test ladder did not catch. Sprint 003 closes both AND adds tests that would catch their recurrence.
- The four deferred items are real but blocked by scope, not skill — each has a named remediation path. They land in v0.2 alongside the Flux backend and Windows bridge work.
- Reviewer's praise of `match_path` on `GRID_MATCHED` and the structured error codes confirms the SDD-discipline-from-the-start choice was correct.

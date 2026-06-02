# BLACKBOARD — cascade-img

*The project's working scratchpad. Seven sections, single-writer per section (sdd-kit-2 discipline). Newest-at-top within each section.*

---

## Surfaced for review

*Agent + Architect. Halts, partial verdicts, comprehension affirmations, observations from the Rubber Duck Pass marked `surfaced`.*

*(empty)*

---

## Decisions

*Architect-only, append-only.*

- **2026-06-02** — **Project scope.** cascade-img is a Python package and MCP server that lets an LLM agent generate, curate, and log Midjourney images autonomously through a Discord self-bot bridge. v0.1 ships the MJ backend; v0.2+ adds Flux / DALL-E / Imagen / other sanctioned APIs behind the same `ImageGenerationBackend` interface. Primary user is an LLM agent inside Claude Desktop / Cursor / Cline / a custom framework; secondary users are sprite artists and indie devs scripting asset generation; tertiary is application developers calling the library from Node/Python. Published under Green Rose Systems LLC at `github.com/greenrosesystems/cascade-img`, PyPI `cascade-img`, npm `@greenrosesystems/cascade-img`. MIT license. ToS posture is honest about the self-bot; pluggable backend exists as the sanctioned escape.

- **2026-06-02** — **Naming convention locked.** Backend-specific scripts get the backend tag (`cascade-mj-bridge` — only MJ needs a bridge daemon). Package-level scripts drop it (`cascade-mcp`, `cascade-mj` for the roll CLI, which is MJ-specific since it goes through the bridge).

- **2026-06-02** — **Curation policy is consumer-controlled, not library-imposed.** The library exposes `crop_grid`, `alpha_key`, `promote` as agent-driveable primitives. Whether the agent or a human picks the winning quadrant is the consumer's call, not the library's. Earlier draft framing that "Architect-only curation" leaked from Katybird's project policy into cascade-img's library policy was reverted.

- **2026-06-02** — **SDD discipline native.** Vocabulary parity, capture-based behavior grading, dual contract run automatically on every change. Validation is not optional and is not surfaced as a question. cascade_img.instrumentation.sdd validates at the speaker's mouth per sdd-kit-2 grammar/PRINCIPLES.md commitment 2. Strict mode is the default; `CASCADE_STRICT_SIGNALS=false` env var is a production release valve, not a permission slip.

- **2026-06-02** — **Vocabulary v0.1 locked.** 27 tags across 11 categories (session, config, bridge, job, discord, backend, curation, composer, log, mcp, cli). Locked-at: 2026-06-02. Edits go through the supervised-grammar-evolution proposal taxonomy and bump the version.

---

## Built

*Agent appends one entry per sprint close, newest-at-top.*

- **2026-06-02** — **Sprint 002 (sdd-kit-2 alignment).** Copied sdd-kit-2 into the project as read-only kit reference. Upgraded `cascade_img.instrumentation.sdd` from a minimal emit/snapshot module to a kit-conformant SignalVocabulary + SignalEmitter with validate-at-emit, `assert_signal`/`assert_no_signal` test primitives, and `format_for_ai()` digest output. Locked vocabulary at v0.1 (`locked: true`, `locked_at: 2026-06-02`). Mirrored `signals/0.1.json` at project root (canonical kit location). Added project-level discipline artifacts: BLACKBOARD.md, WORKING_AGREEMENT.md, KIT_DIARY.md, signals/0.1-rationale.md. Discipline ladder 59/59 green.

- **2026-06-02** — **Sprint 001 (initial v0.1.0a1 port).** Copied the cascade asset pipeline from Katybird/Cascade source folders into the new `cascade-img/` monorepo under Green Rose Systems. Ported: bridge daemon with Config dataclass + MissingEnvError + both Sprint 4.0 patches preserved; MidjourneyDiscordBackend HTTP wrapper conforming to ImageGenerationBackend; PromptComposer with V7 facet composition; PromptLog JSONL ledger; curation kit (crop/alpha-key/promote); structured-envelope MCP server with 10 tools; unified cascade-mj CLI with --dry-run; cascade-mj-bridge --check-env / --doctor; CI workflows; OPERATIONS.md / TOS.md / AGENTS.md / prompts/. Discipline ladder 48/48 green. Names reserved on PyPI, npm, GitHub. (This sprint violated kit hard rule 6's ≤2 files / one concept sweet spot; addressed in the Sprint 002 KIT_DIARY entry.)

---

## Deferred

*Anyone may append.*

- **Live-fire end-to-end smoke.** The discipline ladder verifies everything except a real /imagine fired through a live Discord + Midjourney session. Re-visit when the Architect runs `cascade-mj-bridge` against their real `.env` and reports the resulting signal trace.

- **TypeScript wrapper `@greenrosesystems/cascade-img` beyond placeholder.** Current 0.0.1 is a name-reservation stub. Real implementation (postinstall hook installing the Python engine via `uv tool install`, Zod schemas mirroring Pydantic, Node-native MCP option) is a v0.1 scope item but not yet started. Re-visit before tagging v0.1.0.

- **11-layer vocabulary expansion.** Current `signals/0.1.json` populates Layers 0-2 (lexical + payload) and partial Layer 4 (stratum noted per tag, no explicit temporal_invariants array). Layers 3/5/6/7 (sessions, state_transitions, operators, evidence_constraints) deferred to a Vocabulary v0.2 session. Re-visit when v0.2 ships or when a real drift surfaces a missing invariant.

---

## Open questions

*Anyone may append.*

- **Does PyPI's account-scoped vs project-scoped distinction matter for trusted publishing?** The release workflow uses Trusted Publishing; verify the project trust is configured at pypi.org before tagging v0.1.0.

---

## Drift watchlist

*Agent maintains.*

- **DW-1.** Sprint sweet spot ≤2 files / one concept (kit hard rule 6). Sprint 001's monolithic v0.1.0a1 port violated this. Watch future sprints for the same shape; halt and split if a sprint card declares more than 2 files modified without a clear single-concept reason.

---

## Sprint tail

*Agent maintains. Last 10 sprint closes.*

### 2026-06-02 — Sprint 002 (sdd-kit-2 alignment) closed

**Rubber Duck Pass:**
- Sequence narration: emit-validates is now the default, every test still green; 11 new tests cover the validate-at-emit + assert_signal / assert_no_signal / format_for_ai primitives.
- Observations: no missing pairs, no order violations, no vocabulary gaps, no payload anomalies, no timing surprises, no tone drift.
- Disposition: resolved-here. No surfacings.

Dual contract: pass (signal: 36 emit callsites against 27 vocab tags, parity clean; artifact: 4 new project-level docs + sdd.py upgrade + 11 new tests; observation: ladder ran end-to-end via pytest).

### 2026-06-02 — Sprint 001 (initial v0.1.0a1 port) closed

**Rubber Duck Pass:**
- Sequence narration: 48 tests pass; parity clean; placeholders published; primary smoke (boot-failure capture) confirms MissingEnvError + CONFIG_VALIDATION_FAILED on empty env.
- Observations: One drift (DW-1): sprint sweet spot violated — many files touched in one logical "port" sprint. Surfaced to drift watchlist.
- Disposition: deferred. The discipline going forward is to split sprints; the v0.1 port itself is what it is.

Dual contract: pass (signal: 26 emit callsites against 22 tags at sprint close, parity clean; artifact: package builds, installs, publishes to PyPI/npm/GitHub; observation: ladder green).

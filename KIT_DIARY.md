# KIT_DIARY — cascade-img

*Working diary of what sdd-kit-2's discipline does well, what gets in the way, and what the next kit version should change. Per-sprint or per-phase entries. The diary is the load-bearing artifact that makes kit-improvement insights compoundable across the project's lifetime.*

---

## Hypothesis tracking

| # | Hypothesis | Verdict | Evidence |
|---|---|---|---|
| H1 | The kit's validate-at-emit discipline is worth the migration cost on an already-shipped codebase. | _confirmed_ | All 48 pre-alignment tests continued passing after sdd.py was upgraded to validate-at-emit, because the prior emit callsites already conformed to the declared vocabulary. The migration cost was zero behavioral change; the audit was free. |
| H2 | Operating cascade-img through an LLM-only loop (no human in the room for every roll) actually works in practice. | _pending_ | Live-fire smoke against real MJ deferred (see BLACKBOARD ## Deferred). Will resolve when the Architect runs the daemon against their `.env` and the agent loop completes one full cycle. |

---

## Entries

### 2026-06-02 — Sprint 002 (sdd-kit-2 alignment) closed

**What happened:** The Architect directed the Agent to make cascade-img conform to sdd-kit-2's conventions. The Agent had earlier read the kit in fragments rather than in full; the Architect surfaced this directly. The Agent then read foundations 01-04, grammar/PRINCIPLES + BOOTSTRAP, all templates, lib/sdd.py, and the example/ project. The Agent applied the kit by: copying sdd-kit-2 into the project as a read-only reference, upgrading `cascade_img.instrumentation.sdd` to validate at emit (matching the kit's commitment 2), locking the vocabulary at v0.1, adding BLACKBOARD/WORKING_AGREEMENT/KIT_DIARY/rationale at project root, and writing this entry.

**What worked:**

- The validate-at-emit upgrade was free in behavioral terms. Every existing emit callsite already declared the right payload fields for its tag, because the vocabulary JSON I'd been authoring was internally consistent with how I was emitting. The kit's discipline retroactively validated work that had been done without it.
- The `from_package_data` loader pattern (`importlib.resources.files(...)`) makes the package-bundled vocab the canonical source for the installed wheel, while the project-root copy at `signals/0.1.json` is the kit-conformant canonical for project-level discipline. The two are kept identical.
- `assert_signal` / `assert_no_signal` as test primitives lifted directly into existing test patterns. The tests already snapshotted and looked for tags; the named helpers reduce the boilerplate without changing the verification semantics.

**What got in the way:**

- The Agent surveyed rather than read on the first kit pass. This is a known LLM failure mode (skim what looks templated). The Architect's correction was sharp and correct; the second pass was a full read of each file. **Kit-level note:** the kit's AGENTS.md hard rule 11 ("originals over summaries") is right, but the failure-mode-to-correct is "agent skims kit files as if they were templates" — worth naming as an explicit anti-pattern at the top of the kit's AGENTS.md.
- The kit's BOOTSTRAP procedure is 12 steps and 2.5–4 hours for a fresh project. For a retroactive lock (where the code already exists and the vocabulary has been incrementally evolved across many commits), the procedure overshoots — most of the layers are implicit in the code's existing emit callsites. **Kit-level note:** consider a "retroactive lock" procedure: skip Layers 0/3/4/5/6/7, populate Layers 1/2 from existing emit() AST analysis, surface the gaps as v0.2 proposals.

**What this says about the next kit version:**

- **Finding 1.** "Agent skims kit files as if they were templates" deserves explicit naming in the kit's AGENTS.md or TECHNIQUES.md. The standard fix is: every kit file referenced in a comprehension affirmation must be cited by line range or section, not just by filename — forcing actual read-through.
- **Finding 2.** A retroactive-lock procedure for adoption on existing projects would close the impedance mismatch between BOOTSTRAP's greenfield assumption and the common case (mid-project kit adoption).

---

### 2026-06-02 — Sprint 001 (initial v0.1.0a1 port) closed

**What happened:** The Agent ported the cascade asset pipeline from Katybird's tools/ and the original Cascade/asset_pipeline/ source into the new cascade-img monorepo under Green Rose Systems. The port covered: bridge daemon with structured config, MidjourneyDiscordBackend wrapper, prompt composer, prompt log, curation kit, MCP server, unified CLI, CI workflows, full documentation set. Package built, installed cleanly, published placeholders to PyPI and npm under the LLC. 48 behavior-contract tests landed green on Python 3.10.

**What worked:**

- The sdd-kit-2 discipline (vocabulary first, parity check, behavior-contract tests, structured errors with stable codes and remediation) baked into the port from early on. Even though the kit wasn't formally adopted yet, the principles were being followed because the Agent had absorbed them from Katybird's CLAUDE.md.
- The Sprint 4.0/4.7 production patches (`guild_id` field in `_send_imagine`, `_match_grid` PROGRESS-state fallback) carried over verbatim with comments naming the patch and the failure mode it prevents. The kit's "originals over summaries" principle applied to code, not just docs.
- The decision to split backend-specific naming (`cascade-mj-bridge`) from package-level naming (`cascade-mcp`) was made via a real Architect correction mid-sprint. The kit's "halt and surface" discipline would have caught this earlier; the lesson is to formalize naming conventions BEFORE the port begins, not during.

**What got in the way:**

- **Sprint sweet spot violation.** kit hard rule 6 says ≤2 files per sprint / one concept. This sprint touched 30+ files across 7 commits. The work was a coherent "port" but the kit's rule would have split it into a chain of smaller sprints (one per module: bridge, backend, composer, log, curation, MCP server, CLI, docs, CI). Surfaced to BLACKBOARD ## Drift watchlist as DW-1.
- **Vocabulary materialized incrementally, not as Sprint 0.** Tags were added category-by-category as new modules ported. The kit's Sprint-0 Vocabulary Session (BOOTSTRAP.md) is the canonical pattern; this sprint did the inverse. Mitigated by Sprint 002's retroactive lock.
- **Force-push incident.** The Agent force-pushed to overwrite an initial commit that had the wrong directory layout. The Architect named this as a hard rule violation in the moment. Saved as a feedback memory ("never force-push without explicit approval"); the rule now stands.

**What this says about the next kit version:**

- **Finding 3.** Sprint-0 vocabulary materialization is correct in principle (kit hard rule 12), but the kit needs an explicit "migrating a working but undisciplined codebase" path. Most adopters won't be greenfield; the kit should support retroactive adoption without requiring a full re-architecture pretending the codebase doesn't exist.
- **Finding 4.** The "≤2 files per sprint" rule is empirically grounded (soundfield round 28 finding #100), but porting an existing codebase into a new package layout fights it directly. Either the rule needs a "porting" exception, or the porting work is best done as a single un-sprint-graded bulk move followed by per-module discipline sprints starting at the new layout.

---

## Phase boundary syntheses

*(Insert one synthesis entry per phase close.)*

---

## Project-close synthesis

*(At project close — when v0.1.0 ships and the project moves to maintenance — list the top 5-10 structural findings that should inform the next version of `sdd-kit-`.)*

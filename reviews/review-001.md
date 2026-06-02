> **Review 001 — initial pass (2026-06-01).** First multi-agent documentation/tone/code review.
> Ran against a working tree that was being edited concurrently, so some counts were in flux and a
> few flagged items were fixed mid-run. **Superseded by [review-002](./review-002.md)**, which
> re-verifies every finding against settled code and corrects the PyPI long-description framing.
> Kept for the audit trail.

---

# cascade-img — Documentation & Codebase Review

## 1. Overall verdict

For a v0.1 alpha, cascade-img is **above the norm on prose craft and unusually faithful between docs and code** — the README's "ten tools" and "three console scripts" claims are exact, the Python `PromptComposer` example matches `composer.py` line-for-line, every MCP tool signature quoted in the katybird prompts maps to a real `@mcp.tool()`, and `OPERATIONS.md` is a genuinely excellent runbook. The biggest *strength* is that the engineering substance is real: structured error envelopes, a locked vocabulary with an AST parity checker, `py.typed` shipped, and honest trade-off comments throughout the source. The biggest *liability* is that the repo reads like a confident product-launch page bolted onto a half-published internal lab notebook: the root README over-invests in marketing positioning (a value-laden competitor matrix, "unoccupied ground" superlatives) while *missing* the cheap, expected hygiene files (badges, `SECURITY.md`, `CODE_OF_CONDUCT.md`, issue/PR templates), and ~5x the user-facing volume is internal process material (`sdd-kit-2/`, `BLACKBOARD.md`, `_source/`) that no consumer needs. Compounding both: a recent `signals/ → vocabulary/` rename was only half-applied to prose, leaving dead links and several stale numbers that undercut the doc's own credibility signal. Net: tighten the register, ship the hygiene files, finish the rename, and move the lab notebook off the public surface — none of it is deep, all of it is mechanical.

## 2. Tone & wording

The register is **mostly plain-technical and good** — a marketing-language scan (`blazing|seamless|powerful|robust|elegant`) over `src/cascade_img` returned **zero** hits, and `OPERATIONS.md`/`AGENTS.md`/`CONTRIBUTING.md` read like working engineering docs. The problem is concentrated in the **root README**, which drifts into a self-congratulatory and occasionally adversarial register that none of the respected Python exemplars (FastAPI, Ruff, httpx, Typer, pydantic, Requests, Black) use.

**Grandiose / marketing lines to rewrite:**

- `README.md:83` — *"cascade-img sits one layer up — composition, curation, reproducibility — exactly where the unoccupied ground is."* and *"No other OSS tool treats V7 facets as composable inputs."* This is deck language plus an unverifiable superlative. Ruff's tagline is the target register: *"An extremely fast Python linter and code formatter, written in Rust."* Suggested rewrite: *"Treats Midjourney V7 facets (`--p`, `--sref`, `--oref`, `--ow`) as typed, independently stackable inputs."* State the capability; let the reader infer the differentiation.
- `README.md:115` — *"the discipline ladder ships green."* Opaque jargon-as-boast; a newcomer cannot parse it and it asserts quality rather than showing it. Rewrite: *"the full test suite passes."*
- `README.md:3` & `AGENTS.md:9` — the recurring tagline *"without a human in the room for every roll"* is evocative but tells a newcomer nothing operationally. Replace with the concrete scope already spelled out at `AGENTS.md:27-31` (autonomous for the common case; human needed for initial guidance, failure escalation, and final acceptance).
- `AGENTS.md:148` — the doc closes on an aphorism, *"The mark is recognition, not insight."* It has no operational meaning and reads as house mysticism. None of the reference projects close a contributor- or operator-facing doc with an epigram. Remove it, or replace with an actionable pointer back to `OPERATIONS.md` recovery procedures.

**The competitor comparison table (`README.md:85-97`) is the single clearest convention break.** It is a 12-row scored matrix naming `erictik/midjourney-api`, `novicezk/midjourney-proxy`, and paid proxies, with editorial cells: the *"ToS posture"* row labels cascade-img *"self-bot, explicit and honest"* against a competitor's *"self-bot, hidden"* (`README.md:96`), and another cell reads *"passes raw strings"* (`README.md:88`). That is advocacy, not documentation, and it is also maintenance debt — claims about other projects' capabilities go stale and you won't re-audit them. The strongest Python exemplars deliberately avoid head-to-head named-competitor grids: FastAPI's "Alternatives, Inspiration and Comparisons" page is *praise-first* (it credits what each prior tool did well); Ruff uses a neutral benchmark chart. Recommendation: drop the table, or reframe it FastAPI-style as prior art — and in particular never score a competitor's ToS *honesty*.

**Jargon is used before it is defined.** "V7 facets" appears unglossed in the first paragraph (`README.md:3`); a reader who has never used Midjourney V7 cannot decode `--p`/`--sref`/`--oref`/`--ow` until `AGENTS.md:52`. "Discipline ladder" (`README.md:115`, `CONTRIBUTING.md:24`) is never defined anywhere. "Bring-up ladder" (`README.md:128`) is undefined. The fix already exists in-house: `vocabulary/README.md:14` stops to explain *"Why call it vocabulary"* in plain language — extend that same courtesy to every coined term on first use.

**Voice consistency across READMEs is poor.** The root README is 156 lines of dense feature-marketing; `vocabulary/README.md` is calm and explanatory; `packages/engine/README.md` and `packages/client/README.md` are 5-line placeholders. They do not read as one project's voice. The placeholder is defensible for the **npm** package (a documented v0.2 deliverable), but `packages/engine/` is the artifact `import cascade_img` actually ships from — its README is the long-description PyPI users see on the project page. pydantic, httpx, and Typer all ship a full README as the PyPI long-description; a two-line *"Placeholder release reserving the `cascade-img` name on PyPI. Real v0.1.0 in progress."* undersells the artifact. Point `pyproject`'s `readme` at the root README (once trimmed) or give the engine README a real summary + quickstart.

**One tonal choice that is genuinely good — keep it:** the self-bot risk disclosure. `OPERATIONS.md:5` (*"Accounts get banned. Use a sacrificial Discord account."*) is exactly the blunt register this needs. The only soft spot is **leveling**: `README.md:5` and `TOS.md:8` lead with the normalizing *"this is how every open-source Midjourney tool today works"* before stating the ban risk. State the ban risk first, then the "established pattern" context, so the normalization doesn't lead.

## 3. OSS-convention scorecard

| Convention | Verdict | Note |
|---|---|---|
| Badges (CI/PyPI/Python/license/coverage) | **Misses** | Zero badges in README; CI matrix (`ci.yml:16`), MIT, `requires-python>=3.10`, coverage config all exist to back them. |
| One-line tagline | **Partial** | Strong first 6 words (*"An LLM-operable image-generation pipeline."*) then a ~90-word feature run-on (`README.md:3`). |
| Install section | **Partial** | `pip install cascade-img` is buried inside "60-second quickstart," not its own early `## Installation`. |
| Quickstart honesty | **Partial** | "60-second" oversells; hides a long-running daemon + DevTools token capture (realistically 20-40 min). |
| Comparison-table norm | **Over-does** | Editorial named-competitor matrix; exemplars use neutral benchmarks (FastAPI→TechEmpower, Ruff→chart). |
| Changelog format | **Meets** (w/ defect) | Keep a Changelog 1.1.0 + SemVer stated; `[Unreleased]`/dated/`### Added`; marred by version + count drift (§4). |
| Contributing depth | **Partial** | Good scope/style/PR rules; no top-level dev-setup / `pip install -e ".[dev]"`; test cmd buried and inconsistent with README. |
| Code of Conduct | **Misses** | No `CODE_OF_CONDUCT.md` anywhere. |
| Security policy | **Misses** | No `SECURITY.md` — acute given the tool persists a Discord *user* token (§5). |
| Issue / PR templates | **Misses** | `.github/` has only `workflows/`; no `ISSUE_TEMPLATE/`, no PR template. |
| License | **Meets** | MIT, root + `packages/engine/LICENSE`, README `## License`, `pyproject` consistent (badge missing). |
| Tone / register | **Over-does** | Marketing-leaning root README vs plain-technical norm. |

**Net:** not too sparse — if anything *over-marketed on positioning, under-delivered on standard hygiene files*. The fastest credibility wins are mechanical.

## 4. Factual / consistency issues (verified)

All items below are [confirmed] or [partial] after adversarial re-check. **Note on counts:** reviewers verified the static test count by `def test_` enumeration at **85**; one re-checker running the live parity tool reported **36 tags / 51 emit callsites** and a **78** `def test_` count, diverging from the README's "85" and the commit log's "30 tags / 40 callsites." The numbers are demonstrably in flux — **do not hand-copy a number; generate these figures from a real run and paste the output**, then make every doc cite that single source.

| Issue | File:line | Claimed | Actual | Fix |
|---|---|---|---|---|
| README self-contradicts on test count | `README.md:39` vs `README.md:119`; `CHANGELOG.md:59` | "85/85 green" (line 39) vs "48 passed in 0.5s" (line 119) | Line 39 is current; "48" is a stale Sprint-001 artifact | Regenerate the pasted pytest output from a real run; make line 119 + CHANGELOG agree with line 39. |
| Dead vocabulary link (`signals/`→`vocabulary/` rename, commit 8fc5c4d) | `README.md:115` (clickable link), `CONTRIBUTING.md:17` (inline code), `CHANGELOG.md:51` | links/cites `cascade_img/signals/versions/0.1.json` | file is at `cascade_img/vocabulary/versions/0.1.json`; `signals/` dir gone | Update link text **and** href to `vocabulary/versions/0.1.json` in all three. Only `README.md:115` is a true 404 link; the others are stale text. |
| Stale module/path refs from the same half-applied rename | `OPERATIONS.md:205`, `CHANGELOG.md:49`, `tools/check_vocabulary_parity.py:3`, `tests/vocabulary/test_capture_and_vocab_sync.py:7`, `WORKING_AGREEMENT.md:39,80`, `signals/0.1-rationale.md:137` | `cascade_img.instrumentation.sdd` / project-root `signals/0.1.json` | module is `cascade_img.vocabulary`; `vocabulary/0.1.json` | Global replace; move orphaned `signals/0.1-rationale.md` into `vocabulary/` so the dir isn't a half-rename. (Tool/test code is correct; only docstrings are stale.) |
| CHANGELOG tag count stale | `CHANGELOG.md:51` | "27 tags across 11 categories" | locked JSON has 30 (commit log) / 36 (live tool) — **not** 27 | Regenerate from the parity tool; cite that number. |
| Routing guidance contradicts itself | `AGENTS.md:115-117` vs `OPERATIONS.md:233,238-239` | AGENTS: collision-resistant per-job token routing | OPERATIONS: still describes FIFO/prompt-substring/prefix matching that can swap jobs | Code uses per-job token matching (`bridge.py:474,491,498,516`). Rewrite OPERATIONS "Job sits at submitted" / "Two jobs swapped" sections to token routing; remove substring/disambiguator advice. |
| Upscale output-path scheme contradicts | `AGENTS.md:50` vs `OPERATIONS.md:180-182` | AGENTS: grid `{asset_id}.{png,webp}`, upscales `_u1..u4.png` | OPERATIONS is correct (`bridge.py:592,752`): single upscale → `{asset_id}.png`, grid → `{asset_id}_grid.{png,webp}`, only `--upscale all` → `_u1..u4` | Fix `AGENTS.md:50` to the canonical scheme; AGENTS promises "compute the path before the call returns," so a wrong scheme actively misleads agents. |
| Quickstart `cp` targets a file absent from the installed package | `README.md:31` | `cp .../cascade_img/backends/midjourney_discord/.env.example .env` | no `.env.example` ships in the wheel (`pyproject.toml:87-89` force-includes only `vocabulary/versions/0.1.json` + `py.typed`); real file is repo-level `packages/engine/.env.example` | A pip-only user gets "No such file or directory." Either force-include the template into the wheel, point at a raw-GitHub URL, or inline the ~10 env vars in the README. |
| Quickstart env-var list disagrees with `.env.example` | `README.md:32` vs `packages/engine/.env.example` vs `OPERATIONS.md:52` | README: fill `DISCORD_USER_TOKEN, MJ_CHANNEL_ID, MJ_GUILD_ID, MJ_IMAGINE_VERSION` | `.env.example` has no `MJ_GUILD_ID` (and adds `MJ_IMAGINE_COMMAND_ID`); OPERATIONS calls them "five values"; missing `MJ_GUILD_ID` is the documented `400 Unknown Channel` trap (`OPERATIONS.md:213`) | Pick one canonical env contract; add `MJ_GUILD_ID` (with the Sprint-4.0-trap comment) to the template; reconcile README + OPERATIONS to the file. |
| OPERATIONS cites an error code the bridge never emits | `OPERATIONS.md:83,211,349` | "MISSING_GUILD_ID" surfaced by `--check-env` | `bridge.py:155` reads `MJ_GUILD_ID` as optional, raises no `MissingEnvError`; vocabulary enum omits it (`0.1.json:73`) | Either implement the pre-flight check the doc promises, or state that an unset `MJ_GUILD_ID` is allowed and only fails at runtime as `DISCORD_400_UNKNOWN_CHANNEL`. |
| Version mismatch | `packages/engine/pyproject.toml:7` vs `CHANGELOG.md:7` | `version = "0.1.0"` | only release entry is `[0.1.0a1]`; `pyproject.toml:33` also says "Development Status :: 4 - Beta" — a third disagreeing signal | Pick one: set version to `0.1.0a1` for an alpha ship, or add a `[0.1.0]` CHANGELOG entry. Align the Trove classifier. |
| README `docs/` link is broken | `README.md:132` | `[docs/](./docs/)` | no top-level `docs/`; specs live under `_source/docs/` | Create a curated `docs/`, or repoint/remove the bullet (see §6). |
| `pytest` invocation inconsistent across canonical docs | `README.md:40` vs `CONTRIBUTING.md:24` | `pytest packages/engine/tests/ -v` vs `pytest tests/ -v` | both work from different cwds; `pyproject` `testpaths=["tests"]` assumes cwd=`packages/engine` | State the working directory once; use one invocation form in both docs. |

## 5. Missing documents

| Document | Status | Priority | What it should contain |
|---|---|---|---|
| **`SECURITY.md`** | **Missing** | **High** | The acute gap. The tool extracts a Discord **user token** (full account credential, "Treat as password" — `OPERATIONS.md:58`, `.env.example:4`) and writes it to on-disk `.env`. Needs: (1) a private disclosure channel (GitHub security advisories or `security@`, **not** public issues); (2) supported-versions line; (3) a secrets-handling section — that the token is a full account credential, that `.env` is gitignored (`.gitignore:11`), that `cascade-prompt-log.jsonl` + `generated/` may contain prompts/paths but not the token, and rotation guidance (changing the Discord password invalidates all tokens, `OPERATIONS.md:221`) plus the sacrificial-account advice. Cross-link from README + CONTRIBUTING. |
| `CODE_OF_CONDUCT.md` | Missing | Medium | Contributor Covenant 2.1 with a real enforcement contact; link from CONTRIBUTING. GitHub's community profile flags its absence. |
| Issue templates (`.github/ISSUE_TEMPLATE/`) | Missing | Medium | The bug-report checklist already exists in prose (`CONTRIBUTING.md:53-57`: structured error payload, `--doctor` output, reproducer) — convert to `bug_report.yml`. Add a `feature_request` template referencing the v0.1 out-of-scope list, and a `config.yml` routing security reports to `SECURITY.md`. |
| PR template (`.github/pull_request_template.md`) | Missing | Medium | A discipline checklist: parity tool run, test suite green, vocabulary version bumped if tags changed, ruff clean. |
| `ARCHITECTURE.md` | **Partial** | Medium | A system overview *exists* but is stranded under `_source/docs/CASCADE-MJ-PRODUCT-SPEC.md` §6 with stale pre-extraction names (`cascade_mj`, `cascade-mj-mcp`, `@cascade/mj-client`). Promote a cleaned-up version: component diagram (bridge ↔ `MidjourneyDiscordBackend` ↔ `ImageGenerationBackend` seam ↔ MCP server ↔ CLI), the HTTP endpoints + `{ok, result\|error}` envelope, the in-memory `JOBS` model (restart loses state), and a "how to add a backend" walkthrough. The README calls the HTTP contract "the load-bearing stability seam" (`README.md:151`) but no doc diagrams it. |
| `SUPPORT.md` | Missing | Low | A few lines: bugs → issue tracker; setup questions → OPERATIONS.md then Discussions; security → SECURITY.md. |
| `CITATION.cff` / `GOVERNANCE` | Missing | Low | Optional at single-publisher v0.1. |

Note: `OPERATIONS.md` already discharges the runbook / troubleshooting / FAQ / install-troubleshooting obligations well — those are **not** missing. It would benefit only from being cross-linked as the canonical troubleshooting entry point.

## 6. Repo hygiene / what belongs in a public repo

The repo ships an extraordinary volume of **internal working notes**: `BLACKBOARD.md` (15 KB), `KIT_DIARY.md` (14 KB), `WORKING_AGREEMENT.md` (8 KB), five `sprints/*.md` (~33 KB), `signals/0.1-rationale.md` (10.5 KB), the entire 43-file `sdd-kit-2/` methodology framework (`git ls-files | grep -c sdd-kit-2/` = 43), and a 14-file `_source/` pre-extraction tree. By line count this **dwarfs the user-facing product narrative**, and most of it reads as private notes accidentally published rather than documentation for a consumer:

- `BLACKBOARD.md:3` — *"The project's working scratchpad. Seven sections, single-writer per section (sdd-kit-2 discipline)."* — addresses an internal Architect/Agent dyad, not a user.
- `KIT_DIARY.md:12` — hypothesis H2, *"Operating cascade-img through an LLM-only loop … actually works in practice,"* is publicly marked `_pending_` — i.e. the repo's own committed docs admit the **headline value proposition is unconfirmed** (and it's internally stale: sprint-004 records a completed live smoke).
- `WORKING_AGREEMENT.md:120` publishes a `live_fire_smoke_required` halt condition and a "Drift surface log."

There is genuine **stale/leaky** content here too: `_source/docs/CASCADE-MJ-EXTRACTION-AND-IMPLEMENTATION-PLAN.md` hardcodes the maintainer's local paths 6+ times (e.g. `/Users/<user>/Documents/Claude/Projects/Katybird/`) and uses the obsolete `cascade-mj` / `packages/mj-bridge/` naming ~18 times; `sprints/sprint-004-*.md:131` enshrines a live Discord CDN attachment URL and session sandbox paths as permanent records. The methodology docs reference **phantom sprints** — `BLACKBOARD.md:53` says items closed "in Sprints 006-008" but no `sprint-005`, `sprint-006`, or `sprint-008` card exists; the committed cards jump 004 → 007. That is exactly the audit-trail drift the kit's discipline claims to prevent, which undercuts the case for publishing the process material at all.

To be fair: the methodology docs are well-written and internally coherent (the `sdd-kit-2` README is even self-aware about its scope). The problem is audience and volume, not quality.

**Recommendation (in order):** (1) finish the `signals/→vocabulary/` rename and fix the `docs/` link + test count immediately; (2) move `sdd-kit-2/`, `BLACKBOARD.md`, `KIT_DIARY.md`, `WORKING_AGREEMENT.md`, `sprints/`, and `_source/` out of the published surface — a separate private repo, or at minimum a clearly-disclaimed `internal/` subtree excluded from sdist/wheel; (3) if any stays for transparency, scrub session/CDN identifiers and local paths, and add a one-line README note framing it as build-process archive, not user documentation.

## 7. Code & code-vs-docs notes

The Python is well-built and disciplined: structured `MissingEnvError` carrying `code`+`remediation` (`bridge.py:64-82`), the MCP `_run_tool` envelope faithfully implementing `{ok, result}`/`{ok, error:{code,message,remediation}}` (`mcp_server.py:71-102`), thorough type hints, `py.typed` shipped, honest trade-off comments. Most doc claims verify TRUE (ten tools, three scripts, locked vocabulary + parity tool). The real defects:

- **[High] `cascade-mj` CLI live path is broken.** `cli/mj.py:120` does `await backend.imagine(...)` and `:141` `await backend.wait(...)`, but those backend methods are plain sync `def` returning `dict` (`backend.py:37,46`; `base.py:31`: *"Methods are synchronous at v0.1"*). Awaiting a dict raises `TypeError: object dict can't be used in 'await' expression` — reproduced. One of the three headline entry points fails on its live path. The MCP server gets this right via `asyncio.to_thread`; only the CLI is wrong.
- **[High] That bug is invisible because the non-dry-run path has zero coverage.** Every `run(...)` in `tests/cli/test_mj.py` passes `dry_run=True` (calls at `:90,128,147,165`), which returns at `mj.py:100-115` *before* the broken awaits; the test docstring itself concedes live-fire "is not testable in the discipline ladder." Add one test with a mocked backend returning dicts — it would have caught this.
- **[Medium] `BackendCapabilities` is documented as load-bearing but is entirely unconsumed.** `base.py:18-20` says it's *"Read by the prompt composer … and by the MCP `list_backends` tool,"* but the composer never imports capabilities, nothing reads `.capabilities`, and **no `list_backends` tool exists** (only 10 tools). Either wire it in or trim the docstring to "forward-looking declaration, not yet consumed."
- **[Medium] MCP docstring names a nonexistent script.** `mcp_server.py:8` says *"Start it with the `cascade-mj-mcp` console script"* — the real name is `cascade-mcp` (`pyproject.toml:70`). Copy-pasting gets "command not found."
- **[Low] `promote()` documented as "Move," implemented as copy.** `promote.py:1,16` and `mcp_server.py:223` say "Move," but the body (`promote.py:33-34`) does `read_bytes` + `write_bytes` with no `unlink` — it copies. Copy is the safer behavior for re-rolls; fix the wording to "Copy."
- **[Low] Stray legacy `client.py`.** `backends/midjourney_discord/client.py` has a stale `python mj_client.py` docstring, duplicates `MidjourneyDiscordBackend.imagine`, and is wired to nothing. Delete it or document it.
- **[Low] Backend ABC understates the real contract.** `base.py:35-41` declares only `imagine`/`wait` abstract, but the MCP `status`/`bridge_health` tools call `backend.status()`/`health()` (`backend.py:60,66`). A second backend conforming only to the ABC wouldn't satisfy the MCP surface — add them or document the dependency.

## 8. Prioritized action list

**High**
1. Fix the `cascade-mj` CLI await bug: remove `await` (or wrap in `asyncio.to_thread`) at `cli/mj.py:120` and `:141`.
2. Add a non-dry-run `test_mj` unit test with a mocked backend so the live path is exercised in CI.
3. Add `SECURITY.md` (private disclosure channel + token-handling/rotation policy) — required for a tool that persists a Discord user token.
4. Make the quickstart actually runnable for a pip-only user: ship `.env.example` in the wheel (or inline the env vars / use a raw-GitHub URL) so `README.md:31`'s `cp` resolves.
5. Finish the `signals/ → vocabulary/` rename in prose: fix the dead link `README.md:115` (text + href) and the stale refs in `CONTRIBUTING.md:17`, `CHANGELOG.md:49,51`, `OPERATIONS.md:205`, and tool/test docstrings; relocate `signals/0.1-rationale.md`.
6. Reconcile the env-var contract across `README.md:32`, `packages/engine/.env.example`, and `OPERATIONS.md:52` — add `MJ_GUILD_ID` to the template with the 400-trap comment.
7. Resolve the two operator-facing behavioral contradictions: routing (`OPERATIONS.md:233-239` → token-based) and upscale output paths (`AGENTS.md:50` → canonical scheme).

**Medium**
8. Regenerate all test/tag counts from a real run and make `README.md:119`, `CHANGELOG.md:51,59` agree with `README.md:39` (numbers currently diverge: 85 vs 48 vs 27/30/36).
9. Fix the broken `docs/` link (`README.md:132`) — create a curated `docs/` or repoint/remove.
10. Reconcile the version label: `pyproject.toml:7` (`0.1.0`) vs CHANGELOG `0.1.0a1` vs the "Beta" classifier.
11. Drop or de-editorialize the competitor comparison table (`README.md:85-97`); remove value-laden cells and the ToS-honesty row.
12. Move internal process material (`sdd-kit-2/`, `BLACKBOARD.md`, `KIT_DIARY.md`, `WORKING_AGREEMENT.md`, `sprints/`, `_source/`) off the public surface; scrub local paths / CDN URLs from anything that stays.
13. Add `CODE_OF_CONDUCT.md`, `.github/ISSUE_TEMPLATE/`, and a PR template (content already exists in `CONTRIBUTING.md:53-57`).
14. Add a badge row (CI / PyPI / Python versions / License / coverage) under the README title.
15. Promote a cleaned `ARCHITECTURE.md` from the stranded `_source/docs/` spec.
16. Fix doc-vs-code: `BackendCapabilities`/`list_backends` docstring (`base.py:18-20`); `cascade-mj-mcp` → `cascade-mcp` (`mcp_server.py:8`); remove or implement `MISSING_GUILD_ID` (`OPERATIONS.md:83,211,349`).

**Low**
17. Give `packages/engine/README.md` a real long-description (or point `pyproject.readme` at the trimmed root README); change the npm placeholder to "v0.2 in progress."
18. Add a top-level `## Installation` and a CONTRIBUTING "Dev setup" block (`pip install -e ".[dev]"`); standardize the one `pytest` invocation across README + CONTRIBUTING.
19. Rename "60-second quickstart" to "Quickstart (after env capture)" with one honest sentence on first-time setup time.
20. Lower the README register: replace "discipline ladder ships green," "unoccupied ground," and the closing aphorism (`AGENTS.md:148`) with plain statements; gloss "facets" on first use.
21. Reword the README "prompt templates" claims (`README.md:93,138`) to "worked examples (examples/katybird)" to match CHANGELOG/CONTRIBUTING.
22. Lead the ToS risk statement with the ban risk before the "established pattern" framing (`README.md:5`, `TOS.md:8`).
23. Fix `promote()` "Move"→"Copy" wording; delete or document stray `client.py`; add `status()`/`health()` to the backend ABC or document the extended contract.
24. Add an upscale-modes note to `examples/katybird/README.md` (grid|1|2|3|4|all; omitting returns a 2×2 grid).

> **Review 003 — deep code-quality & test review (2026-06-02).** Python craft, code style, test integrity (do the tests assert what they claim, unit through smoke), and a standardized test taxonomy. All falsifiable findings adversarially verified against HEAD; several earlier leads (the CLI await-on-sync bug, a dead client.py, the `facets` naming) were refuted as already-fixed. Companion to [review-002](./review-002.md).

---

# cascade-img — Deep Code-Quality & Test Review

## 1. First impression / overall craft verdict

Yes — a strong Python engineer reads this and thinks "huh, that's tight." The package presents as the work of one careful author with a real point of view: 100% module-docstring coverage, consistent modern typing (PEP 604 unions, builtin generics, `from __future__ import annotations` on every code-bearing module), a uniform signal-emission discipline woven through every state transition, and — the thing that actually distinguishes it — docstrings and comments that *teach the why and admit the limit* instead of restating the what. `composer.py`, `backends/base.py`, the `bridge.py` resilience layer, and `vocabulary/versions/0.1.json` are genuinely excellent. The places that would make that same engineer wince are narrow and fixable: one schema field that lies about a guarantee the runtime never enforces (the single most damaging defect, because honesty is this codebase's whole pitch), a concurrency race in the daemon's grid handling, a test-collection break under the project's own config, and a cluster of tests that assert against hand-copied reimplementations of the code they claim to cover. None of these are deep design errors; they are the gap between "very good" and "seamless."

## 2. What's already excellent (keep & propagate)

This is the house style. Name these passages in CONTRIBUTING as the bar.

- **Teach the mechanism, not the field.** `composer.py:21-23`: *"Midjourney weights repeated concepts higher, so naming style constraints explicitly … pulls the render in that direction more reliably than a single phrase."* A docstring that explains why the field exists, not what it is.
- **Validate at construction, cite the upstream authority.** `composer.py:49-54, 68-73`: range checks in `__post_init__` with messages like *"must be 0-1000 per Midjourney's --s range; got {self.stylize!r}."* The right validation in the right place with authoritative error text.
- **Admit the limit in the API shape itself.** `backends/base.py:1-8` (*"the speculative surface would harden into something wrong"*) and `backend.py:8-12` (*"wrapping blocking `requests` calls in `async def` would lie about the coroutine contract"*). The sync-vs-async decision is defended as an honesty choice, and `mcp_server.py:79-81` / `cli/mj.py:119-125` actually honor it via `to_thread`.
- **Name the failure mode each algorithm has.** `curation/alpha_key.py:1-22` lays out flood-vs-threshold and the white-penguin-belly-on-white case where *neither* is correct — and `tests/curation/test_alpha_key.py:62-104` pins both the success and the known-bad behavior as a regression contract.
- **Self-aware resilience prose.** `bridge.py:230-234` (why a Discord-timeout job stays claimable, honest about the bill-twice hazard), `bridge.py:383-404` (LRU eviction refuses to drop in-flight jobs and frames dict-growth-past-cap as a deliberate operator signal), `bridge.py:1224-1238` (loop teardown so an in-flight `/imagine` gets a clean `RuntimeError`), `bridge.py:214-218` (why we do *not* call `basicConfig` at import). Library-grade discipline with comments that say why.
- **Per-job token routing.** `bridge.py:246-282` weaves a `--no cscidnocollide{token}` needle into the prompt to route MJ echoes without prefix collisions; `tests/.../test_bridge.py:44-66` proves it routes by token, not substring — directly exercising the collision class Sprint 007 closed.
- **The vocabulary JSON as an ontology.** `vocabulary/versions/0.1.json` is not a tag list; it carries `entities`, `temporal_invariants`, and `state_transitions`, and the per-tag `note` fields read like honest field notes (`JOB_SUBMIT_TIMEOUT`: *"a retry will bill MJ twice if the original did process"*). The single most "tight, interesting" artifact in the tree.
- **Ship the test primitives next to the runtime.** `vocabulary/_runtime.py:185-205`: `assert_signal`/`assert_no_signal` let consumers grade traces with the same vocabulary, and the failure messages dump the tags actually seen, making failures self-diagnosing.
- **A model bug-fix.** `cli/mj.py:119-146` + `tests/cli/test_mj.py:175-231`: a previously-broken await-on-sync path, fixed with `to_thread`, a why-comment, and a **synchronous** stub regression test whose docstring dates and names the exact `TypeError` it guards against. Verified live: the CLI dispatches via `asyncio.to_thread(backend.imagine, …)` (mj.py:123) and the stub is plain `def imagine`/`def wait` (test_mj.py:193,197), so it tests reality.
- **Honest, dated review-trail comments.** `crop_grid.py:46` (*"Review-flagged 2026-06-02 (FD leak on repeated crops)"*), `log.py:121-123` (TOCTOU note). A working engineer's ledger, not noise.

**Leads refuted (for the record):** there is no `client.py` anywhere (confirmed: `find` empty, no imports); the `await backend.imagine` bug is already fixed and the regression test is correctly synchronous; the `upscale_paths` naming is consistent end-to-end; no Python 3.13 classifier is claimed. One cross-finding from a specialist also refuted: the composer emits `prompt_parts_used`, the schema *requires* `prompt_parts_used` (0.1.json:273), and the tests assert on `prompt_parts_used` — these are consistent; there is no `facets_used` mismatch.

## 3. Python craft & correctness

Severity-ordered.

### HIGH — The schema claims a strictness guarantee the runtime never enforces

`vocabulary/versions/0.1.json:88` declares:
```json
{"name": "validator-extras", "value": "strict", "note": "Payload fields not declared in the schema raise at emit; production may relax via CASCADE_STRICT_SIGNALS=false."}
```
But `validate()` (`_runtime.py:62-76`, read in full) only checks for **missing** required fields — it never inspects extra keys. Verified live by the specialist: emitting `PROMPT_COMPOSED` with a bogus extra field is silently accepted and the bogus key lands in the payload. In a project whose entire pitch is "docstrings that admit limitations," a schema that lies about its own strictness is the most corrosive defect in the tree — it breaks the one promise the reader is trusting. Compounding it: every one of the 36 tags carries `"optional_payload": []` (confirmed: 36 occurrences), but nothing in the runtime ever reads `optional_payload` — it is dead schema documenting an intent the code doesn't share.

Fix both at once — make the code true, which also gives `optional_payload` a job:
```python
# _runtime.py validate(), after the missing-field check
required = spec.get("payload", []) or []
missing = [f for f in required if f not in payload]
if missing:
    raise ValueError(f"Event {tag!r} missing required payload fields: {missing}. Required: {required}")
# AFTER — reject undeclared keys so validator-extras=strict is honest:
allowed = set(required) | set(spec.get("optional_payload", []))
extra = [k for k in payload if k not in allowed]
if extra:
    raise ValueError(
        f"Event {tag!r} has undeclared payload fields: {extra}. "
        f"Declared: required={required}, optional={spec.get('optional_payload', [])}. "
        f"Add them to vocabulary/versions/{self.version}.json or drop them."
    )
```
If you decide extras should stay permissive instead, then change the schema line to `"value": "lenient"` and **delete** all 36 `optional_payload` arrays. Either direction is fine; shipping a contract the runtime doesn't honor is not.

### HIGH — `_ingest_message` double-processes a grid under concurrent message+edit dispatch

Both `on_message` and `on_message_edit` dispatch `_ingest_message` via `loop.run_in_executor(None, _ingest_message, …)` (`bridge.py:810, 816`), and the default executor has ~14 worker threads. MJ edits the same grid message repeatedly during render, so two threads can run `_ingest_message` for the same job concurrently. The grid branch at `bridge.py:589-611` (read in full) downloads (unlocked) and then assigns `grid_path` — with **no re-check that another thread already claimed the grid**:
```python
if message.attachments:
    att = message.attachments[0]
    ...
    grid_bytes = _download_to(att.url, grid_path)   # unlocked, racy
    ...
    with LOCK:
        job.grid_url = att.url
        job.grid_path = str(grid_path)
```
The only `grid_path is not None` guards live in `_match_grid` (the `progress_fallback` loop at `bridge.py:560-563` does check it) — but that path is bypassed once `message_id` is set, because `_job_by_message_id` (`bridge.py:557`) returns the job and short-circuits the `_match_grid` call. So Thread A matches the grid, sets `message_id`+`PROGRESS`, starts the unlocked download; Thread B (the edit) gets the same job via `_job_by_message_id`, sees `PROGRESS` + attachments + `grid_path` still `None`, and *also* downloads and fires the U-button presses → double upscale, double MJ bill, two threads racing `status = UPSCALING`. This is exactly the failure class the per-job token killed, reappearing at the edit/duplicate-dispatch layer. Claim the grid exactly once under the lock before any I/O:
```python
if message.attachments:
    with LOCK:
        if job.grid_path is not None or job.status not in (Status.PROGRESS, Status.SUBMITTED):
            return  # another ingest thread already claimed this grid
        job.grid_path = ""  # reserve: marks the grid as being handled
    att = message.attachments[0]
    ...
    grid_bytes = _download_to(att.url, grid_path)
    with LOCK:
        job.grid_url = att.url
        job.grid_path = str(grid_path)
```
The empty-string reservation closes the window between guard and real assignment so a concurrent edit short-circuits.

### MEDIUM — `compose()` accepts an empty/whitespace subject and emits a subject-less prompt

`composer.py:91-96`: `parts = [subject.text.strip()]`. `compose(Subject('   '))` yields `' --ar 1:1 --v 7 --style raw'` — a leading-space prompt with no subject. (Confirmed live, end-to-end: the schema requires `prompt_parts_used`, which the emit supplies, so this is **live behavior, not masked behind an emit error**.) `stylize`/`ow` are validated at construction but `Subject.text` is not, which makes the gap read as an oversight rather than a decision. Add the same construction-time guard the package uses everywhere else:
```python
def __post_init__(self) -> None:
    if not self.text.strip():
        raise ValueError("Subject.text must be a non-empty description.")
```

### MEDIUM — `/wait` crashes with a 500 HTML page on a non-numeric timeout

`bridge.py:1068`: `timeout = float(request.args.get("timeout", "120"))` is unguarded. `GET /wait/<id>?timeout=abc` raises `ValueError` before any try/except → Flask's default 500 HTML, not the JSON envelope agents expect. The package's own `backend.wait()` always sends an int, but the bridge is explicitly designed as a standalone HTTP service. Guard and bound it:
```python
try:
    timeout = float(request.args.get("timeout", "120"))
except ValueError:
    return jsonify(ok=False, error={"code": "INVALID_TIMEOUT",
                   "message": "timeout must be a number of seconds"}), 400
timeout = max(0.0, min(timeout, 600.0))  # a typo can't park a worker thread for hours
```

### LOW — `_download_to` uses `stream=True` then reads `.content`, a no-op that misleads

`bridge.py:530-535` (read in full): `with requests.get(url, …, stream=True) as resp: … data = resp.content`. `stream=True` defers the body, but `.content` then pulls the whole thing into memory — identical profile to `stream=False`, so the flag suggests chunked streaming that isn't happening. Either drop the flag or actually stream to disk:
```python
with requests.get(url, timeout=30, stream=True) as resp:
    resp.raise_for_status()
    with path.open("wb") as f:
        return sum(f.write(chunk) for chunk in resp.iter_content(64 * 1024))
```

### LOW — `Signal.to_dict()` stamps the module-global version, not the emitting vocabulary's

`_runtime.py:106` writes `"vocab_version": VOCAB_VERSION` (hardcoded `'0.1'`), while `format_for_ai` uses the instance's `self._vocab.version` (`:171`). A `Signal` from an `Emitter` holding a non-default `Vocabulary` (e.g. via `from_path()`) would report the wrong version. Latent today; bites the moment a second version is loaded. Carry the version onto the `Signal` at construction so `to_dict()` reflects the actual emitting vocabulary, or document that only one bundled version ever loads.

### LOW — Raise-type inconsistency for the same "unknown tag" condition

`validate()` raises `ValueError` for an unknown tag (`_runtime.py:64-69`), but `category_of`/`stratum_of` (`_runtime.py:78-82`) do bare `self._tag_index[tag][...]` → `KeyError`, which `emit()` then works around with `except KeyError` (`:132`). Pick one. Cleanest: return a sentinel so `emit()`'s guard disappears entirely:
```python
def category_of(self, tag: str) -> str:
    spec = self._tag_index.get(tag)
    return spec["category"] if spec else "unknown"
```

### Perf (LOW, quantified) — `alpha_key` per-pixel Python loops; library duplicates a count the MCP layer already does natively

`alpha_key.py:76-85` (threshold) and `:166-172` (flood post-sweep) iterate every pixel in pure Python and do `keyed += 1`. Benchmarked: 1024×1024 → ~165ms threshold / ~770ms flood; an MJ full-res 2×2 grid (~2k–2.8k px/side) is ~4× that. Meanwhile `mcp_server.py:231` already counts keyed pixels natively: `keyed.getchannel("A").histogram()[0]`. Two independent wins: (1) replace the loop-based count in the library with the same `histogram()[0]` trick (O(1) in Python); (2) vectorize the threshold mask. NumPy isn't a dependency, so the full vectorization is "if you add the dep" advice — but the histogram count needs no new dep and removes the inconsistency between the two layers today. The docstrings already flag flood as the slower path, so this is craft, not correctness.

### Dead strictness, not dead code

No actual dead modules (`client.py` confirmed absent). Function-body imports read as leftover defensiveness rather than need: `mcp_server.py:80` `import asyncio as _asyncio`, `:106` `import asyncio`, `:221` `from PIL import Image` — none breaks a cycle (all top-level deps already imported elsewhere). Hoist them to module scope. `test_alpha_key.py:109` has an `import pytest` inside a test body — move it to the top.

## 4. Code style & consistency

The package is coherent and intentional; the seams are cosmetic but visible to the exact reader the owner is targeting.

### The conceptual core is hostage to the heavy backend through `__init__`

`composer.py` and `vocabulary/` have zero discord/MJ dependency, yet `import cascade_img.composer` pulls `discord` (and stdlib `audioop`) into `sys.modules`, because `composer` imports `cascade_img.vocabulary`, which triggers `cascade_img/__init__.py`, which eagerly imports the discord backend. The conceptual core is the part most likely to be reused standalone (compose a prompt, emit an event); it should be importable without the backend. **Drop the eager backend import from the top-level `__init__`** (make it lazy/optional), so `import cascade_img.composer` and `import cascade_img.vocabulary` are genuinely dependency-free entry points. This is also what turns the test-collection break (§7) from a config patch into a structural fix.

### Bare `dict` breaks the package-wide `dict[str, Any]` convention

Confirmed across two layers (not just `bridge.py` as one specialist framed it): `bridge.py:77` `to_payload() -> dict`, `:1246` `check_env() -> dict`, `:1282` `doctor() -> dict`, params at `:819, :850, :890`, plus `doctor()`'s `checks: list[dict]`; **and** the backend interface shares it — `backends/base.py:45`, `backends/midjourney_discord/backend.py:37,38,46,60,66`. Every other module uses parameterized generics. mypy (`strict=false`) won't flag it. Parameterize them in one pass (`from typing import Any` where missing):
```python
def to_payload(self) -> dict[str, Any]:
async def _post_interaction(payload: dict[str, Any]) -> requests.Response:
def check_env() -> dict[str, Any]:
```

### Flask error envelope is non-uniform

The house contract is `{"ok": bool, "error": {"code", "message", "remediation"}}` (used by `mcp_server._run_tool`, `cli/mj.run`, `check_env`/`doctor`). But most Flask handlers emit flat `jsonify(error="…")` with no `code` and no `ok` (`bridge.py:933, 938, 943, 1019, 1036, 1061, 1073, 1081`); only the `DiscordNotReadyError` path (`:1008`) is structured. The 503-not-ready at `:933` is the sharpest miss — it omits the `DISCORD_NOT_READY` code the `DiscordNotReadyError` docstring *promises operators*. Route every error through one helper:
```python
def _err(code, message, status, remediation=None, **extra):
    body = {"ok": False, "error": {"code": code, "message": message}}
    if remediation:
        body["error"]["remediation"] = remediation
    body.update(extra)
    return jsonify(body), status

if not _ready.is_set():
    return _err("DISCORD_NOT_READY", "discord client not ready yet", 503,
                remediation=DiscordNotReadyError.remediation)
```
If you'd rather keep a flat HTTP shape (status code carries ok/not-ok), that's defensible — but then *document it* in the module docstring as a deliberate divergence, the way this codebase documents its other deliberate divergences. Silent is the only wrong answer.

### Committed source is out of sync with the repo's own formatter

`ruff format --check src/cascade_img` reports **8/18 files would be reformatted** (`backend.py, bridge.py, cli/mj.py, composer.py, alpha_key.py, log.py, mcp_server.py, _runtime.py`). The diffs are hand-wrapped f-strings the formatter collapses (e.g. `composer.py:71-72`, `log.py:84-85`). A contributor who runs the project's declared formatter on a clean checkout gets a diff. Either run `ruff format` and accept the collapsed lines (E501 is already ignored), or wrap the intentional cases in `# fmt: off`/`# fmt: on`.

### Docstring convention is mixed

Mostly plain prose + Sphinx roles, but `curation/` and `log.append` switch to Google `Args:`/`Returns:`/`Raises:` blocks while equal-complexity peers (`composer.compose`, bridge handlers) use prose. Pick one for public callables and state it in CONTRIBUTING — given the prose-forward voice, keep Google blocks only where there are real `Args`/`Raises` to enumerate.

### A short before→after style guide to adopt

| Rule | Before | After |
|---|---|---|
| Parameterize generics | `def to_payload(self) -> dict:` | `def to_payload(self) -> dict[str, Any]:` |
| One error envelope | `jsonify(error="…"), 503` | `_err("DISCORD_NOT_READY", "…", 503)` |
| Formatter-stable strings | hand-wrapped 2-line f-string | single line (E501 ignored) or `# fmt: off` |
| Module-level imports | `from PIL import Image` inside a fn | hoist to top |
| Pick a docstring style | Google in `curation/`, prose elsewhere | one convention, stated in CONTRIBUTING |

### Minor docs-in-code drift (all LOW)

- `alpha_key.py:40` defines `_rgba_components`; `test_alpha_key.py:38` prose says `_rgba`. Update the prose.
- `crop_grid.py:21` comment says `(column_fraction, row_fraction)` but the values are integer `{0,1}` *indices* multiplied by half-width/height at `:67`. Fix: `(col_index, row_index) in {0,1}`.
- `aspect_ratio` (`composer.py:88`) is free-form `str` interpolated straight into `--ar` with no shape check — defensible pass-through, but undocumented. Add one line to `compose()`'s docstring noting it's passed through verbatim, so the absence of a check reads as a decision.

### ruff/mypy config adequacy

ruff lint (`E/W/F/I/B/C4/UP/SIM/RUF`) is a well-chosen set and passes clean on src; the three ignores each carry a one-line rationale (`pyproject.toml:165-169`) — good. mypy is "light" (`strict=false`, `disallow_untyped_defs` unset), which is defensible for Flask/discord callback glue (`http_imagine()`, `on_message(message)` are all untyped) — but combined with bare `dict`, the typed surface the `py.typed` marker advertises is weaker inside the two biggest modules than the rest implies. Minimal close: annotate the return types the framework doesn't dictate (`def http_status(job_id: str) -> ResponseReturnValue:`, `def _signal_handler(signum: int, _frame: object) -> None:`) and parameterize the dicts; leave the framework-dictated params bare but say so once at the Flask banner.

## 5. Test integrity — do the tests do what they say?

The suites are largely honest behavior contracts, not coverage theater. The standout: the alpha_key flood-vs-threshold A/B is a genuine behavioral contrast on one input (flood `0/255/255` vs threshold `0/0/255` for white-interior-in-dark-outline), reproduced by a specialist — exactly the penguin-belly failure the docstring promises. The vocabulary emit contract is properly nailed (unknown-tag and missing-field both raise at the emitter mouth, both verified). The CLI live-path test is a model citizen (sync stub, asserts `calls == ["imagine", "wait"]`, would catch an await-regression). The parity test runs the real AST-walker and asserts `rc==0`. The asyncio dispatch mocks correctly `coro.close()` the un-awaited coroutine to avoid the `-W error` escalation.

But several test **names/docstrings claim a stronger guarantee than the assertion delivers**, and one whole block tests a copy of the code.

| Test | Claims | Actually asserts | Gap | Fix |
|---|---|---|---|---|
| `test_partial_press_failure_keeps_job_upscaling` + 3 siblings (`test_bridge_resilience.py:462,493,522,539`) | "behavior contract for the resilience layer"; per-slot upscale isolation | A **hand-copied reimplementation** — `_press_partial_failures_via_gather` (`:436-453`) mirrors `bridge.py:690-716`, and the bookkeeping/terminal-code is re-derived inline (`:482-490, :514`). Docstrings admit it ("Mirrors the gather() result loop"). `_ingest_message` is **never called by any test** (confirmed by grep). | The ~250-line orchestration core (download, grid save, UPSCALING state machine, press-failure branching, completion) has zero production-path coverage; the real logic could drift arbitrarily and all four stay green. This is also exactly where the §3 race would surface. | Extract `_classify_press_results(slots, results)` and `_apply_press_outcome(job, …) -> str|None` from `_ingest_message`; call them from both the daemon and the tests, then delete the copy. Add one test driving the real `_ingest_message` with a fake message + monkeypatched `_download_to`/`run_coroutine_threadsafe`, including a **concurrent-dispatch** case. |
| `test_full_style_stack_includes_all_flags` (`test_composer.py:46-51`), `test_identity_stack_appends_oref_and_ow` (`:63-64`) | "Validates v7 prompt-string assembly across the four facet combinations" | `"--p …" in p` substring checks. Only the subject-only case (`:22`) uses `==`. | Flag **order and spacing** are unpinned in the full-stack path; a reorder or double-space passes. | Pin the full string: `assert p == "a small finch --ar 16:9 --v 7 --style raw --p … --sref … --s 50"`. Soften the docstring to "representative combinations" or expand to the sub-facets. |
| (no test exists) | `StyleStack.stylize`/`IdentityStack.ow` "validated at construction" (`composer.py:38-39, 49-54, 68-73`) | Nothing — grep finds no out-of-range stylize/ow test anywhere. | An off-by-one in `not 0 <= x <= 1000` goes undetected. | `with pytest.raises(ValueError, match="--s range"): StyleStack(stylize=1001)` + boundary cases (`0` and `1000` accepted). Same for `ow`. |
| `test_append_then_read_roundtrip`, `test_read_last_n` (`test_log.py`) | `PromptLog` "Append-only … Thread-safe" (`log.py:54`) | Single-instance sequential appends only. No concurrent/interleaved write, no cross-instance reopen. | The `Lock` is never exercised; "Thread-safe" is an unverified claim. | Add an 8-thread × 50-append test asserting `len(read()) == 400`, plus a reopen-same-path test proving appends don't truncate. |
| `test_releases_source_file_after_return`, `test_zero_returns_copy_not_the_loader` (`test_crop_grid.py:63-80`) | "must not hold a file descriptor on the source" | Unlink then read a pixel. On POSIX, unlinking an open-FD file succeeds and loaded pixels stay readable — so these pass *even if the FD leaked*. | They verify copy-materialization, not FD release. | Rename to `test_result_survives_source_deletion`, or run the suite once under `pytest -W error::ResourceWarning` so an unclosed PIL fp surfaces. |
| `promote` overwrite (no test) | docstring: "overwrites the destination if present" (`promote.py:3-5`) | Nothing writes a pre-existing dest then promotes over it. | The re-roll-replaces-prior-promotion promise is unproven. | Write `b"OLD"` to dest, promote `b"NEW"` src, assert dest == `b"NEW"`. |
| `test_doctor_reports_all_checks` (`test_cli_bridge.py:74-91`) | "four known checks, pass or fail" | Only that the four check *names* are present + `BRIDGE_DOCTOR_RAN` fired. | No check's `ok` is asserted; an import-error regression making `mcp_server_importable=False` passes. | Assert `ok is True` for the three deterministic checks (`env`, `mcp_server_importable`, `discord_self_importable`); leave `discord_reachable` unasserted as the comment notes. |
| MCP `imagine`/`wait`/`status`/`bridge_health`/`alpha_key` (no test) | file header "Behavior contract for the MCP server tools" | These five tools are never called. `alpha_key` ships a load-bearing `keyed_ratio` reject band (`mcp_server.py:216-219`) nothing checks. | The tools an agent *branches on* have no assertion. | Monkeypatch `_backend` with a sync stub (the `test_mj.py` pattern), assert the `{ok,result}` envelope + `MCP_TOOL_*`; feed `alpha_key` a synthetic PNG and assert `keyed_ratio` lands in band. |
| `test_capture_and_vocab_sync.py:80-84` | drift guard between root + package vocab | `pytest.skip` when root file absent | Skip fires the same way for a *deleted dev-tree file* as for an installed wheel — the guard vanishes exactly when divergence is likeliest. | `if (pkg_root / "src").is_dir(): pytest.fail(...)` else skip — keeps the wheel escape hatch, fails in source checkouts. |

Smaller honesty items, all LOW: `test_sdd_vocabulary.py:27` comments "27 tags as of v0.1.0a1" while the real count is **36** (confirmed) and it asserts only `>= 27` — a floor of 27 against 36 lets a 9-tag regression slip; pin `== 36`. The `deque(maxlen=5000)` buffer eviction (a real silent drop-oldest behavior) is untested — add a tiny `max_buffer=3` eviction test. Composer subject/constraint normalization (strip + empty-skip, `composer.py:91-96`) has no behavioral witness — add one `"  finch  "` + `["", "  side view "]` test.

## 6. Test taxonomy & standardized terminology

The suite is genuinely good — 114 docstringed test functions across 15 modules, fast, isolated, with docstrings that name *what contract* each file pins. The weakness is purely **tiering**, and the house terms are mostly honest but inconsistent with industry terms.

### House term → standard term

| House term (where) | Standard term | Honest? |
|---|---|---|
| "behavior contract" (most module docstrings) | **unit** | Mostly accurate — these are unit tests. |
| "discipline ladder" (commits/CHANGELOG) | the full unit suite as a gate | Fine as a project nickname; not a tier. |
| "smoke walk" (`tools/smoke_mcp_walk.py`) | **e2e** — its own line 1 says "Live end-to-end"; ~2-3m upscale-all run | Mislabeled. "Smoke" should be a fast subset; this is the full live path. |
| `app.test_client()` `/imagine` cases (`test_bridge_resilience.py:290,319,348`) | **integration** (in-process WSGI boundary) | Mislabeled — lumped under "behavior contract" with pure-unit cases. |
| `test_parity.py`, `test_root_and_package_vocab_files_are_identical` | **contract** (cross-artifact gate) | The genuine contracts. |

### Proposed marker set (register in `pyproject.toml`)
```toml
[tool.pytest.ini_options]
markers = [
    "unit: fast, in-process, no network/subprocess/real-Discord. The default tier.",
    "integration: crosses an in-process boundary (Flask test_client, MCP fn dispatch) but stays hermetic — no live external service.",
    "contract: cross-artifact consistency gate (emit-sites vs vocabulary, root-mirror vs package-data). Fast; runs with unit.",
    "smoke: fast happy-path slice of the live walk; needs a real .env. Skipped by default.",
    "e2e: full live walk over the real MCP stdio transport + real Discord/Midjourney. Slow, costs credits. Skipped by default.",
]
```

### File → marker
| File | Marker |
|---|---|
| `test_composer`, `test_log`, `test_sdd`, `test_sdd_vocabulary`, `test_capture_and_vocab_sync` (capture cases), `test_alpha_key`, `test_crop_grid`, `test_promote`, `test_config`, `test_cli_bridge`, `test_mj`, `test_mcp_server`, `test_bridge` | `unit` |
| `test_bridge_resilience` — the three `app.test_client()` `/imagine` cases | `integration` (mark per-function; leave backoff-math/classifier/eviction `unit`) |
| `test_parity::test_parity_clean`, `test_capture_and_vocab_sync::test_root_and_package_vocab_files_are_identical` | `contract` |
| `tools/smoke_mcp_walk.py` (folded into `tests/e2e/test_smoke_walk.py`) | `e2e` (+ a fast `smoke` variant) |

### Directory / naming
Keep the existing `tests/` mirror of `src/cascade_img/`. Add one leaf: `tests/e2e/test_smoke_walk.py`. Keep `test_*.py` / `test_*` naming. Reserve "smoke" for the fast live subset, "e2e" for the full walk.

### Running each tier
```bash
pytest -m "not e2e and not smoke"   # fast default — the CI gate, no .env needed
pytest -m integration               # in-process boundary only
pytest -m contract                  # vocabulary parity + mirror identity
CASCADE_LIVE=1 pytest -m smoke       # fast live happy path; needs real .env
CASCADE_LIVE=1 pytest -m e2e         # full live walk
```
CI: default job runs `pytest -m "not e2e and not smoke"`; a separate manual/nightly job with sacrificial credentials sets `CASCADE_LIVE=1` and runs `-m "e2e or smoke"`. A contributor with no `.env` gets green.

### Fold the smoke walk in
```python
# tests/e2e/test_smoke_walk.py
import os, pytest
pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(os.environ.get("CASCADE_LIVE") != "1",
                       reason="live e2e walk — needs CASCADE_LIVE=1 and a real .env"),
]
def test_smoke_walk_grid_only():
    from tools import smoke_mcp_walk
    assert smoke_mcp_walk.main(["--wait-timeout", "120"]) == 0
```
Keep the script for hand-runs (`main(argv)` is already parameterized). This makes the e2e path collectible, reportable, and skipped-by-default. Also finish the conftest migration: `scrubbed_env` (`conftest.py:36`) is **defined but used by zero tests**, while `test_config.py:32` and `test_cli_bridge.py:21` hand-roll their own `_scrub`/`_scrub_env` duplicating the same var list — either delete the dead fixture or replace the local helpers with it, so the docstring's "centralizes the env-scrubbing pattern several modules need" becomes true.

## 7. Tooling & CI config

The config is mostly good (branch coverage on, strict-config, a well-chosen ruff set), but it ships with a collection break under its own settings.

### HIGH — `filterwarnings=["error"]` + discord.py-self's audioop import breaks all test collection on 3.11/3.12

`pyproject.toml:113-122` (confirmed) sets `filterwarnings = ["error", "ignore::UserWarning:discord", "ignore::DeprecationWarning:mcp", "ignore::DeprecationWarning:pydantic"]`. discord.py-self does an unconditional `import audioop` at import time (`discord/player.py`, reached via `from .player import *`), which raises `DeprecationWarning: 'audioop' is deprecated` on 3.11/3.12. Because `composer`/`vocabulary` route through the top-level `__init__` that eagerly imports the backend (§4), **every** test module that imports `cascade_img` aborts at collection — multiple specialists independently reproduced "11 errors during collection" / "6/6 assigned modules errored," and confirmed `-W ignore::DeprecationWarning` makes the full suite pass, so the test *logic* is sound and the config is the sole blocker. The project's own "85/85 green" was run on a toolchain where this didn't fire. Critically: the module-anchored forms (`ignore::DeprecationWarning:audioop` and `ignore::DeprecationWarning:discord`) **do not** catch it — the warning's deepest frame is attributed to `discord.player`/the audioop import frame, and pytest's anchored module matching misses it. Only the **message-match** form works (verified by two reviewers, 7/7 and 40-passed):
```toml
filterwarnings = [
    "error",
    "ignore::UserWarning:discord",
    "ignore::DeprecationWarning:mcp",
    "ignore::DeprecationWarning:pydantic",
    # discord.py-self hard-imports the stdlib audioop module at import time
    # (PEP 594: deprecated 3.11/3.12, removed 3.13). Match by message — the
    # warning is attributed to the audioop import frame, not the discord
    # package, so a module-anchored filter misses it and collection dies.
    "ignore:'audioop' is deprecated:DeprecationWarning",
]
```
The structural fix in §4 (don't route `composer`/`vocabulary` through a backend-importing `__init__`) is the deeper remedy; the message-match filter is the one-line patch that unblocks the suite today. Do both.

### MEDIUM — `requires-python = ">=3.10"` has no upper bound; pip on 3.13 installs then crashes at import

`pyproject.toml:11`. audioop is *removed* in 3.13, so `import discord` → `ModuleNotFoundError`. The classifiers correctly stop at 3.12, but pip resolves on `requires-python`, not classifiers — a 3.13 user installs successfully then fails at import. Cap it: `requires-python = ">=3.10,<3.13"`, turning a confusing runtime error into an honest pip resolution error. Re-raise the ceiling when discord.py-self drops the audioop import or vendors `audioop-lts`.

### LOW — `--strict-markers` guards nothing

`pyproject.toml:111` enables `--strict-markers` + `--strict-config`, but no project markers are registered — the only marker used is `asyncio`, which pytest-asyncio auto-provides (and `asyncio_mode = "auto"` means even that decorator is unnecessary). The flag is decorative until §6's marker set lands. Register the markers (which makes strict-markers a real guard and gives CI a fast tier) **or** drop the flag as cargo-cult strictness. Registering is the better move.

## 8. Prioritized action list

**High**
- Enforce `validator-extras=strict` in `validate()` (reject undeclared payload keys, allowing `optional_payload`) — or relabel the schema and delete the 36 dead `optional_payload` arrays. The honesty contract is the whole pitch; do not ship a schema the runtime doesn't honor.
- Close the `_ingest_message` grid race: claim the grid once under `LOCK` (empty-string reservation) before any download/U-button press, so a concurrent message+edit can't double-bill.
- Add the message-match `"ignore:'audioop' is deprecated:DeprecationWarning"` filter so the suite collects on 3.11/3.12; structurally, stop routing `composer`/`vocabulary` through a backend-importing top-level `__init__`.
- Drive the real `_ingest_message` (or an extracted `_classify_press_results`/`_apply_press_outcome` helper) from tests and delete `_press_partial_failures_via_gather`; include a concurrent-dispatch case that would catch the race above.

**Medium**
- Add a `Subject.__post_init__` non-empty-text guard (the empty-subject prompt is live behavior, not masked).
- Guard and bound the `/wait` timeout parse so a non-numeric query param returns a JSON 400, not a 500 HTML page.
- Unify the Flask error envelope to `{ok, error:{code,message,remediation}}` (and emit the promised `DISCORD_NOT_READY` code) — or document the flat HTTP shape as deliberate.
- Parameterize bare `dict` → `dict[str, Any]` across `bridge.py` and the backend interface; run `ruff format` (or `# fmt:off`) so a clean checkout is diff-free.
- Cap `requires-python = ">=3.10,<3.13"`.
- Register the unit/integration/contract/smoke/e2e marker set, tag the suite, and set the default CI lane to `pytest -m "not e2e and not smoke"`.

**Low**
- Pin full prompt strings in the full-stack/identity composer tests; add the missing stylize/ow boundary tests, the promote-overwrite test, an interleaved-write `PromptLog` test, the buffer-eviction test, and MCP coverage for `imagine`/`wait`/`status`/`bridge_health`/`alpha_key`.
- Pin the tag count `== 36` and fix the stale "27 tags" comment.
- Use `histogram()[0]` for the keyed-pixel count in the alpha_key library (drop the loop count); fix the `stream=True`+`.content` no-op.
- Resolve the `validate()`/`category_of` `ValueError`-vs-`KeyError` inconsistency with a sentinel return.
- Hoist function-body imports (`mcp_server.py` asyncio/PIL, `test_alpha_key.py` pytest) to module scope.
- Fold `tools/smoke_mcp_walk.py` into a skipped-by-default `tests/e2e/test_smoke_walk.py`; finish or delete the `scrubbed_env` conftest fixture; make the vocab-sync drift guard `fail` in source checkouts instead of skipping.
- Fix docs-in-code drift: `_rgba` → `_rgba_components`, `QUADRANT_OFFSETS` "fraction" → "index", document `aspect_ratio` as verbatim pass-through; carry `vocab_version` onto the `Signal` (or document the single-version assumption).

# Wave F — Live MCP Walk (operator-eye findings)

**Date:** 2026-06-02. **Operator:** LLM acting as an agent host (Claude Desktop/Cursor
equivalent), driving cascade-img end-to-end against the live Midjourney v7 account through
the MCP tool surface only (except reading PNGs with vision and reading the raw-capture file).

**Transport:** one-shot stdio MCP client `/tmp/cascade-live-out/mcp_call.py`
(`mcp` python SDK, `stdio_client` + `ClientSession`), env `CASCADE_BRIDGE_URL=http://127.0.0.1:5057`,
`CASCADE_PROMPT_LOG=/tmp/cascade-live-out/prompt-log.jsonl`. Bridge launched from the .env
directory with `PORT=5057 MJ_OUTPUT_DIR=/tmp/cascade-live-out CASCADE_CAPTURE_RAW=...`.

---

## Did the loop close unaided?

**Yes.** The full operator loop — compose_prompt → imagine → wait → (vision-verify the PNG)
→ curate (score_grid, contact_sheet, crop_grid, alpha_key, auto_trim, palette_quantize) →
log_append → read_prompt_log — closed entirely through the MCP surface with no
out-of-band intervention, **once the bridge connected**. The one thing that blocked the
loop at the start was a real dotenv bug (see Bug 1) that made the documented launch contract
silently fail; after fixing it the bridge connected on the first health poll and everything
downstream worked.

Concrete evidence:
- `imagine` → job_id `049c3cb9c29049af9af873951c46f30c`, status `submitted`.
- `wait(timeout=360)` → `done` in ~30 s; record carried `grid_path`, `image_path`,
  `upscale_message_id=1511317210822611026`, `mj_job_uuid=383afba5-...`, `upscale_paths={"1": ...}`.
- Files on disk: `livebird_grid.webp` (317,892 B), `livebird.png` (389,450 B),
  `livebird_keyed.png` (440,771 B), `livebird_trim.png` (320,246 B), `livebird_pal.png`
  (77,541 B), `livebird_q1.png` (288,114 B), `livebird_contact.png` (1,331,121 B).
- Vision check confirmed real images: a 2x2 grid of distinct pixel-art birds; U1 upscale a
  grey/white bird with red crest, orange beak/feet on white; the alpha-keyed+trimmed result
  rendered the bird on transparency, tightly cropped.
- `alpha_key` (flood) keyed_ratio **0.7976** — within the documented healthy sprite band
  (0.4-0.8), so the agent could trust the key without re-rolling.
- `score_grid` ranked slot 3 best (composite 1.0), slot 2 worst (0.0) — usable evidence
  for candidate selection.
- log_append → read_prompt_log round-tripped the record byte-identically.
- All 6 `mj_action` families pressed successfully and produced derived results.

---

## Tool surface verification

`list_tools` advertised **16 tools**, all with input schemas:
compose_prompt, imagine, wait, status, bridge_health, mj_action, crop_grid, alpha_key,
promote, contact_sheet, auto_trim, palette_quantize, sprite_sheet, score_grid, log_append,
read_prompt_log.

- 15 tools have populated `properties`. `bridge_health` has empty `properties` — correct
  (it takes no args); not confusing for an LLM caller.
- Required-field sets are sensible: `imagine` requires `prompt`+`asset_id`; `mj_action`
  requires `job_id`+`action`; curation tools require `src` (+`dest` where they write).
- No schema would mislead a caller. `compose_prompt`'s 18 optional params are well-named
  and documented in its docstring.

---

## Ergonomic vs awkward

**Ergonomic:**
- `compose_prompt` → `imagine` → `wait` is a clean three-call pipeline; `wait` returns the
  full job record so the agent never has to poll `status` separately.
- The `{ok, result}` / `{ok, error:{code,message,remediation}}` envelope is consistent
  across every tool and trivial to branch on.
- `alpha_key` returning `keyed_ratio` with documented interpretation bands is exactly the
  kind of self-describing signal an LLM needs to decide promote-vs-reroll without vision.
- `mj_action` returning the resolved live `custom_id` in its result is great for an operator
  log/audit — you can see precisely which button fired.

**Awkward / friction:**
- **Nested envelope on `mj_action`.** Because `mj_action` proxies the bridge's
  `/action` HTTP response (which is itself `{ok, result}`) and `_run_tool` wraps it again,
  the MCP result is `{ok:true, result:{ok:true, result:{...}}}` — a double-nested
  `result.result`. Every other tool is single-level `{ok, result}`. A caller must know to
  unwrap twice for `mj_action`. Minor, but inconsistent. (Severity: low.)
- **No tool surfaces the derived-result of an action.** `mj_action` fires the button and
  returns the custom_id, but the vary/zoom/pan/animate output lands as a fresh, untracked MJ
  message. v0.1 documents this ("does not route it to a child job"), but operationally the
  agent has no MCP way to retrieve the animate webp it just produced — it would have to
  watch the channel itself. This is precisely the Wave F receive-side gap; the capture this
  run produced is the input to closing it.
- **`wait` default timeout is 180 s** but a cold MJ grid can take ~30 s and an upscale adds
  more; for the loop I passed 360. Fine, just worth knowing the default may be short for
  upscale jobs.

---

## Envelope / schema / AGENTS.md drift actually hit

- No schema drift: the advertised inputs matched the documented behavior for every tool I
  called.
- One **doc drift** worth fixing: `RUNBOOK.md` says "Drop a `.env` file in the working
  directory of `cascade-mj-bridge`." That instruction is only true after Bug 1 is fixed —
  with the pre-fix bare `load_dotenv()`, the cwd `.env` is ignored when the bridge runs via
  its console script. The fix makes the RUNBOOK instruction correct; no doc change needed
  beyond shipping the fix. (Could optionally document the new `CASCADE_DOTENV` override.)

---

## Bugs

### Bug 1 (HIGH, FIXED) — `Config.from_env()` bare `load_dotenv()` ignores cwd under the console script

**Where:** `packages/python/src/cascade_img/backends/midjourney_discord/bridge.py`,
`Config.from_env()`.

**Symptom:** `cascade-mj-bridge --doctor` (and the daemon) launched from the .env directory
reported `MISSING_DISCORD_TOKEN` even though the `.env` was present and valid in cwd — the
documented launch contract. `python -c "...main()"` from the same cwd succeeded; the
console-script binary failed. Reproducible.

**Root cause:** python-dotenv 1.2.2's `load_dotenv()` with no path delegates to
`find_dotenv()`, which only uses `os.getcwd()` when `__main__` has no `__file__` (the `-c`
/ REPL case). Under the **console-script entry point**, `__main__.__file__` IS set
(`.venv/bin/cascade-mj-bridge`), so `find_dotenv` instead walks frames up to `bridge.py`,
takes that module's directory, and `_walk_to_root`s upward from the installed package — never
reaching the cwd `.env`. The token reads as missing and **the live connection never starts**.
This silently defeats the entire "launch with cwd = the .env directory" contract for the
real (entry-point) launch path while passing the in-process unit tests.

**Fix applied:**
```python
dotenv_override = os.environ.get("CASCADE_DOTENV")
if dotenv_override:
    load_dotenv(dotenv_override)
else:
    load_dotenv(find_dotenv(usecwd=True))   # honor cwd regardless of how we're launched
```
(`from dotenv import find_dotenv, load_dotenv`.) After the fix, `--doctor` returns `ok:true`
via the console script and the daemon connected (`discord_ready:true`) on the first health
poll. **163 passed / 2 skipped, ruff clean.**

**Suggested follow-up:** document `CASCADE_DOTENV` in RUNBOOK.md as the explicit-path escape
hatch for hosts that can't control the daemon's cwd (e.g. launchd/systemd units).

### Bug 2 (LOW, FIXED) — raw-capture `event` tag couldn't ride on `discord.Message`

**Where:** the Wave F capture hook + `on_message_edit`, same file.

**Symptom:** the first hook revision set `after._cascade_capture_event = "edit"` before
dispatch. `discord.Message` is `__slots__`-based (40 slots, no `__dict__`), so the assignment
raised `AttributeError`, was swallowed by the hook's `suppress`, and **every captured line
fell back to `event="message"`** — even genuine in-place progress edits. (The authoritative
86-line capture has this limitation; it is noted in `wave-f-receive-capture.md`. Captures are
otherwise complete.)

**Fix applied:** `_ingest_message(message, event="message")` now takes the event as a call
argument; `on_message_edit` passes `"edit"`. Verified live in a second short run:
`raw-capture-verify.jsonl` shows `{"message": 2, "edit": 6}`. Backward-compatible — existing
test call sites call `_ingest_message(msg)` positionally and get the default.

### Observation (not a bug) — animate is an animated WEBP, not mp4

Worth flagging for whoever builds the receive-side download path: `animate_*` returns
`content_type: image/webp`, an animated webp (125 frames, infinite loop), `duration: null`.
Any future "video" handling must not assume mp4/`video/*`. Also: Discord CDN attachment URLs
need the signed `ex/is/hm` query string preserved and a real HTTP client (`requests` works;
`urllib` 403'd). The bridge's existing `_download_to` (requests-based) is correct for this.

---

## Net assessment

The MCP surface is coherent and an operator can run the whole compose→imagine→curate→log
loop through it unaided. The single hard blocker was a real, shipped dotenv bug that broke
the documented launch path on the entry-point; it is now fixed and the live loop is green.
The remaining structural gap is the one Wave F exists to close: pressed-action derived
results (vary/zoom/pan/animate) are not retrievable through MCP yet. The receive-side capture
from this run (`reviews/wave-f-receive-capture.md` + `wave-f-raw-capture.jsonl`) gives the
matchers a clean, observed parent-link signal (`message_reference.message_id == upscale_message_id`,
present on all six families) to build on.

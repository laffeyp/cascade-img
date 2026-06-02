# Wave F — live end-to-end verification (real Midjourney account)

Date: 2026-06-02. Live run against the real MJ account
(`funtaclularbunnicala6767`, id `1502242966100639815`, channel
`1502243953687265485`). Goal: confirm the daemon still boots/connects after the
large bug-fix pass, and that the fixes hold *live* — especially the receive-side
derived-result routing (only fixture-tested before) and that strict enum
enforcement did not turn any real emit into a crash.

All artifacts under `/tmp/cascade-live-verify/`. Bridge log copied to
`reviews/wave-f-live-verify.bridge.log` (70 lines, 8 KB). Full daemon log scanned
for crash markers — none found.

Run config (CASCADE_STRICT_SIGNALS left UNSET → strict enum enforcement ACTIVE):
`PORT=5057`, `MJ_OUTPUT_DIR=/tmp/cascade-live-verify`,
`CASCADE_JOB_DB=/tmp/cascade-live-verify/jobs.db`, cwd = the `.env` directory so
the daemon's own `load_dotenv(find_dotenv(usecwd=True))` found the secrets (the
bridge read the token itself; it was never echoed).

## Boot + connect — PASS

`GET /health` returned `discord_ready:true` on the first poll. Bridge log shows a
clean startup, no traceback:

```
05:18:15,619 Connected to Gateway (session ID: 842f1884c960526e34c1950155910aa2).
05:18:15,723 Discord connected as funtaclularbunnicala6767 (id=1502242966100639815)
05:18:15,724 Watching channel 1502243953687265485
```

## MCP client — PASS

`mcp_call.py list` over stdio (`cascade-mcp`, `CASCADE_BRIDGE_URL=http://127.0.0.1:5057`)
returned exactly **16 tools**: alpha_key, auto_trim, bridge_health, compose_prompt,
crop_grid, imagine, log_append, mj_action, palette_quantize, promote,
read_prompt_log, score_grid, sprite_sheet, status, wait.

## Full loop, upscale="all" — PASS

`compose_prompt` → `imagine(asset_id="verifybird", upscale="all")` →
`wait(timeout=600)`. job_id `ed6c39d32af34cdc8b4a11ef06048ad6`. Completed in ~34s.

- 4/4 upscale slots landed; `upscale_pending: []`, `upscale_press_failures: {}`.
- `len(upscale_message_ids) == 4` → `{1:1511343447360143391, 2:1511343435930533969, 3:1511343434122657903, 4:1511343447091449978}`.
- **Canonical-agreement fix [9] holds:** `image_path` = `verifybird_u3.png` (slot 3),
  and `upscale_message_id` = `1511343434122657903` = `upscale_message_ids["3"]`.
  The canonical SOLO message id is the slot that produced `image_path`.
- Files on disk (all PNG 1024x1024, real bytes):
  - `verifybird_u1.png` 480178 B
  - `verifybird_u2.png` 199599 B
  - `verifybird_u3.png` 214245 B  (canonical)
  - `verifybird_u4.png` 621096 B
  - `verifybird_grid.webp` 365560 B (RIFF WebP)
- Vision check on `verifybird_u3.png`: a genuine 8-bit pixel-art bird sprite
  (red/grey robin, yellow throat, standing) on white. Real MJ output, not a placeholder.

## Live receive routing (the key new thing) — PASS

Each `mj_action` was fired via MCP, then `/status` was polled until `Job.derived`
gained a new entry with a non-empty path and bytes>0; each file then confirmed on
disk at that size. Final `Job.derived` (from `/status`), as
`action_kind:filename:bytes:content_type`:

| # | action_kind | file | bytes | content_type | message_id | mj_uuid |
|---|---|---|---|---|---|---|
| 1 | variation | verifybird_variation_fad7ead8.webp | 283420 | image/webp | 1511343699953451129 | fad7ead8-... |
| 2 | animation | verifybird_animation_a14ec42c.webp | 1872462 | image/webp | 1511344023296806983 | a14ec42c-... |
| 3 | variation | verifybird_variation_ef1713ff.webp | 213964 | image/webp | 1511344241253548133 | ef1713ff-... |

### (a) vary_strong on canonical SOLO — PASS + single-level envelope confirmed

MCP result was single-level:
`{"ok":true,"result":{"action":"vary_strong","custom_id":"MJ::JOB::high_variation::1::93fdd28c-8ef2-4ed2-9381-16f68ff5247a::SOLO","job_id":"...","message_id":1511343434122657903}}`
— `result["result"]["action"]=="vary_strong"`, NO `result["result"]["result"]`
nesting. The backend unwraps the bridge envelope and `_run_tool` wraps once.
Derived entry #1 (variation grid, 283420 B image/webp) routed home in ~12-15s;
`saved derived variation` logged at 05:20:18.

### (b) animate_high — PASS, content_type image/webp (NOT video/mp4)

Pressed `animate_high` (custom_id `MJ::JOB::animate_high::1::93fdd28c-...::SOLO`).
Derived entry #2 landed at **t+~59.6s** after the press. `action_kind="animation"`,
content_type **`image/webp`**, 1872462 B (~1.87 MB). File header confirms a true
animated WebP: `RIFF...WEBPVP8X` with an `ANIM` chunk and `ANMF` frame chunks. So
MJ delivers the animation as an animated webp, not an mp4 — the classifier and
router handle it correctly. `saved derived animation` logged at 05:21:35.

### (c) vary_strong slot=2 (non-canonical SOLO, fix [8]) — PASS

`mj_action(..., slot=2)` returned `message_id=1511343435930533969`, which equals
`upscale_message_ids["2"]` and is DISTINCT from the canonical `upscale_message_id`
(`1511343434122657903`, slot 3). Its custom_id carries slot 2's own uuid
(`87370d9b-...`), distinct from slot 3's (`93fdd28c-...`) — proof it targeted the
slot-2 surface, not the canonical one. Derived entry #3 (a fresh variation grid,
213964 B image/webp) then routed home to the SAME parent job via
`_job_by_upscale_message_id` matching `message.reference.message_id` against
`upscale_message_ids.values()`. `saved derived variation` logged at 05:22:27.

## Enum-enforcement safety — PASS

Strict enum enforcement was active the entire run (`CASCADE_STRICT_SIGNALS` unset
→ default true at vocabulary-runtime import). Full bridge.log grep for
`ValueError | "outside its locked enum" | Traceback | "Unknown event tag"`:
**NONE**. Every live emit (`IMAGINE_FIRED`, `GRID_MATCHED`, `GRID_RECEIVED`,
`UPSCALE_*` ×4, `MJ_ACTION_REQUESTED` ×3, `MJ_DERIVED_RECEIVED` ×3, `JOB_COMPLETED`,
`BRIDGE_HEALTHY`) carried in-enum values; in particular `MJ_DERIVED_RECEIVED.action_kind`
took only `variation` / `animation`, both inside the locked enum
`{animation, pan, upscale, variation, zoom}`. No ingest thread crashed. Final
`GET /health` returned `discord_ready:true` — daemon stayed healthy through teardown.

## Notes / minor observations (not blockers)

- `match_path == "progress_fallback"`: MJ posted the final grid as a NEW message
  (1511343427445329920) rather than editing the preamble it first matched
  (1511343309153501294 via "pending"); the grid-fallback matcher claimed it
  correctly. Expected behavior, exercised live.
- The `INTERACTION_SUCCESS referencing an unknown interaction ID ... Discarding`
  WARNINGs in the log are discord.py-self gateway noise (it doesn't track our raw
  POST /interactions presses); they are not bridge emit errors.
- `MJ_DERIVED_RECEIVED.parent_message_id` was observed as `null` in one transient
  `/status` read of an in-flight entry, but routing did not depend on it — every
  entry landed on the correct parent job via the message_reference match, and the
  final persisted `derived` entries carry full path/bytes/content_type/uuid. The
  parent reference is informational only.

## Verdict

Boot, connect, full upscale="all" loop, canonical agreement [9], single-level
mj_action envelope, live receive-side routing for variation + animation +
non-canonical slot-2 [8], image/webp animation (not mp4), and strict enum
enforcement safety: all verified live with real files on disk. No failures.

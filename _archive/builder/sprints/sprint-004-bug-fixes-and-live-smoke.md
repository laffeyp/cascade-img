# Sprint 004 — Bug fixes and live smoke

---

```yaml
---
id: 004
status: closed
phase: 2
pass_kind: functional
opened: 2026-06-02
closed: 2026-06-02
---
```

---

## scope

Two pieces. First, end-to-end live smoke against the running Discord/Midjourney session: start the bridge with the live `.env`, fire one `/imagine`, watch the job to terminal state, capture the resulting state. Second, act on the second external code review delivered 2026-06-02: 7 bugs across concurrency, resource leaks, and input validation. Land all 7 fixes, add 4 tests covering the fixes, re-run the discipline ladder.

---

## prerequisites

- Sprint 003 closed; discipline ladder at 64/64.
- Live `.env` accessible at `/sessions/<sandbox>/mnt/asset_pipeline/.env`.
- Bridge code at v0.1.0a1.

---

## context_files

- The review text (delivered inline, 2026-06-02).
- `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` (3 bugs: lines 432, 548, 404).
- `packages/engine/src/cascade_img/log.py` (1 bug: line 94).
- `packages/engine/src/cascade_img/mcp_server.py` (1 bug: line 206).
- `packages/engine/src/cascade_img/curation/crop_grid.py` (1 bug: line 46).
- `packages/engine/src/cascade_img/curation/alpha_key.py` (1 bug: line 54).

---

## signal contract

### Emits

No new vocabulary tags. The fixes operate on existing emit paths.

### Invariants

- Discipline ladder remains green throughout.
- No deletions (kit hard rule 12).
- No force-push.
- The live smoke uses `MJ_OUTPUT_DIR=/tmp/smoke/generated` and `PORT=5001`; output stays out of the project tree.

---

## artifact contract

### Files modified

- `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py`:
  - `_download_to` wraps `requests.get` in `with ... stream=True:` so the Response is closed deterministically (fix #6).
  - Path-A match in `_ingest_message`: the `job.message_id` / `job.status` / `job.touch()` mutations move under `with LOCK:` (fix #1).
  - Path-B upscale completion in `_ingest_message`: all post-download mutations (`upscale_paths`, `image_path`, `image_url`, `upscale_pending.remove`, `touch`) move under `with LOCK:` (fix #2).
- `packages/engine/src/cascade_img/log.py`:
  - `PromptLog.read` replaces `exists()` + `read_text()` with `try / except FileNotFoundError` under the lock (fix #3).
- `packages/engine/src/cascade_img/curation/crop_grid.py`:
  - `crop_quadrant` tracks `opened_here`, materializes via `img.copy()` for the `quadrant=0` path, and closes the source loader in a `finally` (fix #5).
- `packages/engine/src/cascade_img/curation/alpha_key.py`:
  - Pixel access guarded by a `_rgba(pixel)` helper that tolerates 3- or 4-channel returns from `convert("RGBA")` (fix #7).
- `packages/engine/src/cascade_img/mcp_server.py`:
  - `alpha_key` MCP tool wraps `Image.open(src)` in a `with`-statement so the loader closes (fix #4).
- `packages/engine/tests/test_log.py`:
  - Add `test_read_handles_concurrent_deletion` covering the TOCTOU fix.
- `packages/engine/tests/test_curation.py`:
  - Add `test_alpha_key_corners_handles_rgb_input` covering the channel-count guard.
  - Add `test_crop_quadrant_releases_source_file_after_return` covering the FD-release fix.
  - Add `test_crop_quadrant_zero_returns_copy_not_the_loader` covering the `quadrant=0` materialization.

### Content assertions

- `grep -q "with requests.get" packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` matches (fix #6).
- `grep -q "with LOCK:" packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` matches in two new locations (fixes #1 and #2).
- `grep -q "except FileNotFoundError" packages/engine/src/cascade_img/log.py` matches (fix #3).
- `grep -q "opened_here" packages/engine/src/cascade_img/curation/crop_grid.py` matches (fix #5).
- `grep -q "_rgba" packages/engine/src/cascade_img/curation/alpha_key.py` matches (fix #7).
- `grep -q "with Image.open" packages/engine/src/cascade_img/mcp_server.py` matches (fix #4).

### Command exit codes

- `python3 -m build` returns 0.
- `pip install dist/cascade_img-0.1.0a1-py3-none-any.whl[dev]` returns 0.
- `python3 tools/check_vocabulary_parity.py` returns 0.
- `pytest tests/` returns 0 with **68 passing** (64 prior + 4 new).
- `git push origin main` returns 0.

---

## observation contract

### Live-fire smoke (executed 2026-06-02 04:20 UTC)

Steps:

1. Source the live `.env` into the bash environment; override `MJ_OUTPUT_DIR=/tmp/smoke/generated`, `PORT=5001`.
2. Start `cascade-mj-bridge` in background, redirect output to `/tmp/bridge.log`.
3. Poll `GET /health` until `discord_ready=true`.
4. `POST /imagine` with `prompt = "pixel-art sprite of a tiny grey finch, side view, transparent background --ar 1:1 --v 7 --style raw"`, `asset_id = "smoke_v1"`.
5. Poll `GET /status/<job_id>` every 2 seconds until terminal.

Recorded results:

| t (s) | status | progress |
|---|---|---|
| 0 | submitted | — |
| 4 | progress | queued |
| 10 | progress | 17% |
| 14 | progress | 30% |
| 16 | progress | 35% |
| 20 | progress | 47% |
| 24 | progress | 67% |
| 26 | progress | 83% |
| 28 | done | 100% |

Final `/status` payload:

- `status: done`
- `match_path: progress_fallback`
- `grid_path: /tmp/smoke/generated/smoke_v1.webp`
- `grid_url: https://cdn.discordapp.com/attachments/<channel-id>/<message-id>/...`
- File on disk: 261986 bytes.

### Expected signals during live smoke

The daemon emits (only the daemon-side signals are visible; client-side `BACKEND_HTTP_CALLED` is not in this trace because the bridge was driven via curl, not `MidjourneyDiscordBackend`):

- `CONFIG_VALIDATED`
- `CASCADE_INIT`
- `DISCORD_CONNECTED`
- `BRIDGE_HEALTHY` (multiple)
- `IMAGINE_FIRED`
- `GRID_MATCHED` with `match_path="progress_fallback"`
- `GRID_RECEIVED`
- `JOB_COMPLETED`

---

## done criteria

7 bug fixes landed; 4 new tests covering them; discipline ladder 68/68 green; live smoke completed with the daemon producing a 261986-byte grid at `/tmp/smoke/generated/smoke_v1.webp`; commit and normal push.

---

## notes

- The live smoke's `match_path: progress_fallback` value records which code path inside `_match_grid` produced the match for this specific MJ V7 response.
- The reviewer's bug #2 (`list.remove(idx)` without bounds check) was already guarded by `if idx in parent.upscale_pending:` in the single-threaded path; the real exposure is concurrent removal. The fix wraps the whole post-download block under `LOCK`, which closes both the bounds check race and the broader torn-read window.

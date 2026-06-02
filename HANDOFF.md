# Handoff — cascade-img

_As of 2026-06-02. Read this first when picking the project back up._

## Release status (the headline)

- **v0.1 is BUILT, live-verified end-to-end, and entirely on `main`** — and it overshoots its promised scope.
- **v0.1 is NOT RELEASED.** There is no git tag, `CHANGELOG.md` is still `## [Unreleased]`, and nothing is published to PyPI. It's a finished build sitting un-cut.
- **To cut v0.1** (operator-side, ~4 steps): (1) finalize `CHANGELOG.md` `[Unreleased] → [0.1.0] + date`; (2) `git tag v0.1.0 && push the tag`; (3) set up PyPI trusted publishing for `cascade-img`; (4) publish the wheel (`python -m build` already produces `cascade_img-0.1.0`, shipping the vocab catalog + `py.typed`).
- **v0.2+ not started** (see Next steps).

## v0.1 scope: promised vs. delivered

| Promised (README roadmap) | State |
|---|---|
| MJ V7 backend, facet composer, curation kit, MCP server, AGENTS.md, Python package | done |
| **Beyond scope, also shipped** | response-message actions (`mj_action`: upscale/vary/zoom/pan/animate/favorite) + derived-result routing into `Job.derived`; `score_grid`; `contact_sheet`/`auto_trim`/`palette_quantize`/`sprite_sheet`; rembg alpha-key (`[ml]` extra); SQLite job store (restart recovery) |

## Architecture (one paragraph)

Composer (named prompt parts → MJ v7 string) → locked **SDD vocabulary** (`emit()` validated at the callsite, incl. enum enforcement) → `backends/midjourney_discord` = a thin HTTP client + a Flask/`discord.py-self` **bridge daemon** (the only thing touching Discord) → curation kit, JSONL prompt log. Two front doors — `cascade-mcp` (MCP, 16 tools) and `cascade-mj` (CLI) — speak HTTP to the bridge; the bridge drives Discord → Midjourney. Console scripts: `cascade-mj-bridge`, `cascade-mcp`, `cascade-mj`.

## Quality bar — keep it green (run from `packages/python/`)

```
ruff check . && ruff format --check . && mypy src/cascade_img && pytest \
  && python tools/check_vocabulary_parity.py \
  && diff ../../vocabulary/0.1.json src/cascade_img/vocabulary/versions/0.1.json
```
Current: **182 passed / 2 skipped**, ruff+format+mypy clean (all enforced gates), parity **47 vocab tags / 67 emit callsites**, vocab mirror byte-identical, wheel builds clean.

## Live verification (how to re-run)

`cd packages/python && CASCADE_LIVE=1 CASCADE_ENV_FILE=<live .env> pytest -m e2e`. The bridge reads its `.env` from its working directory, or set `CASCADE_DOTENV=<abs path>`. Use `PORT=5057` (macOS AirPlay squats on 5000). Last live run: **full PASS** — boot+connect, `upscale="all"`, vary/animate/slot actions all routed to disk, single-level `mj_action` envelope, zero emit-enforcement crashes under strict mode. Evidence: `reviews/wave-f-live-verify.md`. Receive-side ground truth (what MJ actually echoes): `reviews/wave-f-receive-capture.md` + `reviews/wave-f-raw-capture.jsonl`.

## Pushing to the remote

`origin` = `github.com/greenrosesystems/cascade-img`. The machine's gh/git account (`laffeyp`) does **not** have access to that org repo, so a plain `git push` 404s. Push with the repo owner's GitHub PAT:
```
git push "https://<PAT>@github.com/greenrosesystems/cascade-img.git" HEAD:main
```
Scrub the token from any printed output; never commit it. (Committing is local and always works — only push needs the PAT.)

## Non-negotiables & gotchas

- **No Claude/AI attribution** anywhere — commits, PRs, files.
- **ToS:** Discord and Midjourney prohibit user-account automation; the operator owns that exposure (`TOS.md`). v0.1 is local-only — no hosted SaaS.
- The bridge is a single Flask dev-server daemon (in-memory `JOBS` + SQLite write-through sidecar) over `discord.py-self`.
- `MJ_IMAGINE_VERSION` drifts when MJ updates the slash command — re-capture when `DISCORD_400_OUTDATED` appears (`RUNBOOK.md`).
- The receive side routes derived results by `message_reference == upscale_message_id` — **never recency** (the MJ channel is shared). animate lands as an animated **WebP**, not mp4.

## Recent hardening

An adversarial bug hunt fixed **14 confirmed bugs**: upscale-result race (double-complete), error-envelope flattening, dropped CLI timeout signal, non-atomic downloads, executor-pool deadlock/starvation, per-slot upscale map + `slot=` targeting, phantom-job rehydration, runtime enum enforcement, divergent alpha_key flood semantics, broken `cascade-mcp --http`. mypy was promoted to a required gate.

## Next steps (priority order)

1. **Cut the v0.1 release** (the 4 steps above).
2. **v0.2:** TypeScript wrapper (currently a placeholder, `@greenrosesystems/cascade-img` `0.0.1`); Flux-via-Fal + OpenAI `gpt-image-1` backends; Windows bridge.
3. **Cross-backend image relay** — chain providers, feeding one's output into another's input (roadmap).

## Repository map

- **Product:** `packages/python/` (`import cascade_img`). Tests: `packages/python/tests/`. Tools: `packages/python/tools/`.
- **Docs:** `README`, `ARCHITECTURE`, `RUNBOOK`, `AGENTS`, `RUNDOWN`, `CHANGELOG`, `TOS`, `CONTRIBUTING`.
- **`reviews/`** = audit trail (code/doc reviews, live captures, verification reports). **`_archive/`** = builder history, not shipped.
- **Vocabulary:** `packages/python/src/cascade_img/vocabulary/versions/0.1.json` (byte-identical mirror at `vocabulary/0.1.json`).

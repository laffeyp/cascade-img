<!-- Generated from the AGENT-ORIENTATION block in AGENTS.md by packages/python/tools/render_agent_entrypoints.py.
     Do not edit by hand — edit that block in AGENTS.md and regenerate. -->

## What cascade-img is, and how you drive it

**What it is.** cascade-img is an LLM-operable image-generation pipeline — Midjourney through a Discord bridge at v0.1, with pluggable backends (Flux, DALL-E, Imagen, …) behind one interface after. **You, the agent, are its primary operator:** it is built so you compose a prompt, generate, curate the winner, and log the attempt without a human on every roll.

**The loop, per asset.** `compose_prompt → imagine → wait → inspect (read the PNG with vision) → curate (crop_grid → [alpha_key?] → promote) → log_append`. Open each iteration with `read_prompt_log(n=5)` — the append-only log is your working memory across rolls.

**The shape — one daemon, two entry points, all over local HTTP:**
- `cascade-mj-bridge` — the daemon, and the only process that talks to Discord. It must be running.
- `cascade-mcp` — the MCP server exposing 16 tools; this is how you, the agent, drive everything.
- `cascade-mj` — the CLI, for scripting and one-off rolls.

**The 16 MCP tools, by job.** *generation* — `imagine`, `wait`, `status`, `bridge_health`, `mj_action`; *composition* — `compose_prompt`; *curation* — `crop_grid`, `alpha_key`, `auto_trim`, `palette_quantize`, `contact_sheet`, `sprite_sheet`, `score_grid`, `promote`; *working memory* — `log_append`, `read_prompt_log`. Every call returns `{ok, result}` or `{ok: false, error: {code, remediation}}` — branch on the stable `code`, never the message.

**Where to go next.**
- [RUNBOOK.md](../RUNBOOK.md) — install, the Discord `.env` values to capture, bring-up, and every failure mode with its error code and fix. Read this to set up or to recover.
- [CAPABILITIES.md](../CAPABILITIES.md) — every Midjourney v7 prompt parameter and `mj_action`, with ranges and effects.
- [README.md](../README.md) — the overview and why cascade-img exists.
- [examples/](../examples/) — two end-to-end walkthroughs: one image, and a batch sharing one style.
- [AGENT_RUNDOWN.md](../AGENT_RUNDOWN.md) — a paste-in prompt that has an LLM read the source and brief you from it.

**The one constraint.** cascade-img drives Midjourney through a Discord *user* account; both services' Terms of Service prohibit that automation, and the human who configured the daemon has acknowledged it. Treat a persistent token rejection (`DISCORD_401` after re-capture, or `DISCORD_RECONNECT_FAILED(reason=auth)`) as a structural failure that needs the human — the daemon cannot self-recover.

**Full operator guide:** [AGENTS.md](../AGENTS.md) — the complete tool reference, the v7 prompt-part details, identity-lock guidance, and the failure-mode→action table.

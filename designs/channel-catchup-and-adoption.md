# Channel catch-up and message adoption (v0.2 design)

> **Status: implemented on main (2026-07-17)**, with these v1 scope decisions against the
> design as written below:
>
> - **Kinds simplified** to `grid | solo | video | other` (no `video_grid`/`video_solo`
>   split — the artifact-type distinction lives in the attachment record).
> - **Adopted grids are artifact-only.** U-results are matched by routing token +
>   `UPSCALING` state + pending slots, not by reply reference, so a retro-U-press on an
>   already-done adopted job has no verified route home. Deferred until that routing is
>   captured live (a `crop_grid` quadrant is pixel-equivalent on a V8.1 `--hd` render).
>   Adopted SOLOs and videos are fully actionable as designed (their results reply to the
>   adopted message).
> - **The ring buffer is in-memory** (200 records); a cold buffer after a daemon restart
>   falls back to one REST history page rather than persisting the buffer.
> - `channel_recent` is exempt from the `cascade_guide` gate (orientation, read-only);
>   `adopt_message` is gated (it mutates the job table).
> - Extra error codes beyond the table below: `INVALID_N`, `MISSING_ASSET_ID`,
>   `INVALID_MESSAGE_ID`.

The human is the director: they watch the agent drive Midjourney and step in whenever they
want — pressing U4 by hand, firing a Vary, typing their own `/imagine` in the channel. Today
the pipeline is blind to all of it. The bridge routes only the jobs it submitted, so anything
human-initiated never reaches the job table, the output directory, or the prompt log. The
agent's working memory silently diverges from what actually happened in the channel.

This design closes that gap with two bridge routes, two MCP tools, and one log convention.

**Evidence (2026-07-17 hero-image session).** The operator pressed U4 on a tracked job's grid
by hand. The resulting "Image #4" SOLO was invisible to every tool; the agent had to fetch it
with raw Discord REST calls outside the pipeline. Related v0.1 limits hit in the same session:
a vary/zoom/pan result that is itself a grid is recorded in `derived` but not re-tracked, and
a grid-only job can never be acted on after the fact (`NO_UPSCALED_IMAGE`, no retro path).
Adoption is the single mechanism that fixes all three.

---

## The two tools

### `channel_recent(n=10, before=None)` — read-only catch-up

Returns the last `n` Midjourney-bot messages from the configured MJ channel as structured
records, newest first:

```json
{
  "ok": true,
  "result": {
    "messages": [
      {
        "message_id": "1527832887016030219",
        "kind": "solo",                      // grid | solo | video_grid | video_solo | moderation | other
        "prompt_text": "cinematic triptych, ...",
        "routing_token": "f5e59382",          // parsed from --no cscidnocollide<token>; null if absent
        "tracked_job_id": "04076cf6...",      // resolved when the token matches a job; null = human-initiated or foreign
        "slot_label": "Image #4",             // MJ's own label when present
        "attachment": {"url": "...", "width": 3104, "height": 1552, "content_type": "image/png"},
        "buttons": ["vary_subtle", "vary_strong", "zoom_out_2x", "pan_left", "..."],
        "created_at": 1784334512.1
      }
    ]
  }
}
```

- Scope is hard-bounded: the configured `MJ_CHANNEL_ID` only, Midjourney-bot messages plus the
  operator's own slash-command invocations, `n` capped at 50. This is not a Discord browser.
- `buttons` lists the action surfaces present on the message (marker-matched, same mechanism
  `mj_action` already uses), so the agent knows what an adoption would unlock before adopting.
- `tracked_job_id` is the catch-up primitive: `null` means "this happened without you."

### `adopt_message(message_id, asset_id)` — claim a result into the job table

Creates a tracked job from an existing MJ message, exactly as if the bridge had submitted it:

1. Bridge fetches the message, classifies its kind, downloads the artifact to
   `<output_dir>/<asset_id>.<ext>` (the normal deterministic path).
2. A job record enters the table (and the SQLite mirror) with `origin: "adopted"`,
   `status: "done"`, the message id as its action surface, and the parsed routing token if any.
3. Everything downstream works unchanged: `status`/`wait` read it, curation tools take its
   paths, and — because the message's live button `custom_id`s are readable — **`mj_action`
   works on it**. Retro-upscale on an old grid, vary on a hand-pressed SOLO, re-tracking a
   derived vary/zoom/pan grid: all of these are "adopt, then act," not separate features.

Adopting a grid registers its U1–U4 surface; adopting a SOLO registers the vary/zoom/pan/
animate surface; adopting a video grid registers `video_upscale` slots. One mechanism.

### Log convention — human-initiated events

Adoption appends a prompt-log record so working memory stays truthful:

```json
{"asset_id": "...", "origin": "human_in_discord", "agent_decision": null,
 "prompt": "<echoed prompt text>", "job_id": "<adopted job id>", "outputs": {...}}
```

`read_prompt_log` consumers treat `origin: human_in_discord` as "the director stepped in here."

---

## Bridge changes

| Piece | Change |
|---|---|
| Message ring buffer | The gateway handler already sees every channel message; keep the last 200 MJ-bot messages (id, content, attachments, components) in a bounded deque. No disk. |
| `GET /channel/recent?n=&before=` | Serve structured records from the ring buffer; fall back to one Discord REST page when the buffer is cold (fresh daemon start). |
| `POST /adopt/<message_id>` | Body `{asset_id}`. Fetch → classify → download → insert job (`origin: "adopted"`). Idempotent per message id. |
| `mj_action` | No route change — adopted jobs carry their message id as the action surface, the existing button-location path applies. |
| Job store | Add `origin` column (`submitted` \| `adopted`); rehydration unchanged. |

## Error codes (stable, per the envelope)

| Code | Meaning | Remediation |
|---|---|---|
| `MESSAGE_NOT_FOUND` | id not in channel history | check `channel_recent` output for the right id |
| `NOT_AN_MJ_MESSAGE` | message isn't from the MJ bot or has no artifact | only MJ results are adoptable |
| `ALREADY_TRACKED` | message belongs to an existing job (or was already adopted) | act on the existing `job_id` returned in the error payload |
| `ADOPT_DOWNLOAD_FAILED` | artifact fetch failed | retry the adopt |
| `CHANNEL_READ_FAILED` | Discord REST/history error | retry after a short delay; `DISCORD_401` escalates as usual |

## Event catalog additions (`vocabulary/0.2`)

- `CHANNEL_CATCHUP_READ` — payload `n`, `returned`, `untracked_count`. Fires per `channel_recent`.
- `MESSAGE_ADOPTED` — payload `message_id`, `asset_id`, `kind`, `had_routing_token`. Fires per adopt.
- `JOB_FAILED` gains the five codes above.

## Acceptance criteria

1. Operator presses U4 by hand → `channel_recent(5)` shows the SOLO with `tracked_job_id: null`
   and its button list → `adopt_message` returns a job whose artifact exists at the deterministic
   path → `mj_action(job, "vary_strong")` on it returns a derived grid. End-to-end, no raw REST.
2. Adopting the same message twice returns `ALREADY_TRACKED` with the original `job_id`.
3. A vary-derived grid recorded in `derived` can be adopted and its quadrants acted on —
   closing the v0.1 "derived grids not re-tracked" limit.
4. `channel_recent` never returns content from any channel other than `MJ_CHANNEL_ID`.
5. Every adopt appends a prompt-log record with `origin: "human_in_discord"`.

## Out of scope

Arbitrary Discord browsing, multi-channel support, adopting non-MJ content, webhooks/push
(clients still poll), and automatic adoption (the agent decides; nothing is claimed silently).

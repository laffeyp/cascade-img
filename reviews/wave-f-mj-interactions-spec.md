> Research spec for Wave F (drive every Midjourney response-message action). Produced by the mj-response-buttons-research workflow; grounded against the bridge seams at HEAD. Implementation reference, not user docs.

---

# Wave F — Drive Every Midjourney Response-Message Action Programmatically

**Status:** implementation spec (grounded against `packages/engine/src/cascade_img/backends/midjourney_discord/bridge.py` @ `0.1.0`, vocabulary `0.1`, `mcp_server.py`).
**Scope:** make every button/affordance on a Midjourney response message drivable with no human clicking.

---

## 0. Load-bearing facts about the current bridge (these gate every row below)

These are read from the code, not assumed:

- **The bridge does NOT hardcode custom_ids.** It reads them at runtime off `message.components`. The single hardcoded regex `UPSAMPLE_BTN_RE = MJ::JOB::upsample::(\d+)::([0-9a-f-]+)` (line 406) is used *only* by `_extract_mj_uuid` (line 545) to pull the MJ job UUID — never to *construct* a press. The actual press payload (line 690) reuses `f"MJ::JOB::upsample::{n}::{mj_uuid}"` only because the bridge already knows `n` and `mj_uuid`; for every Wave F action the press must instead take the literal `custom_id` straight off the live component. **Every spec row below assumes custom_ids are discovered at runtime.** Do NOT invent custom_id literals; the formats cited in the research (e.g. `MJ::Outpaint::...`, `MJ::CustomZoom::...`, `MJ::RemixModal::new_prompt`, `low_variation`/`high_variation`) are *recognition hints for matching*, not values to construct.
- **The press primitive is generic already.** `_press_button(message_id, custom_id, guild_id)` (line 905) POSTs interaction `type=3` (MESSAGE_COMPONENT), `data.component_type=2` (BUTTON). Any plain button is pressable the instant its `custom_id` is read.
- **Three capabilities the bridge lacks today** (the gating work):
  1. **No MODAL_SUBMIT path** (interaction `type=5`). Needed for Custom Zoom, Remix-on Vary/Reroll/Pan/Variation, Animate Manual, Extend Manual.
  2. **No mask-submit path** (synthesize + base64 a PNG mask). Needed for Vary (Region).
  3. **Result ingest is PNG- and grid/upscale-shaped.** `_ingest_message` (line 556) downloads `message.attachments[0]`, derives `ext` via `os.path.splitext` defaulting to `.png` (lines 611, 776), and routes results by either the prompt-echo token `cscidnocollide{token}` (`_match_grid`, line 477) or `Image #N` + MJ uuid (`_match_upscale`, line 504). Any action whose result is a **new grid**, a **new single image**, or a **video (.mp4)** needs new result-routing, and video additionally needs a content-type branch on download.
- **`_safe_output_path` already preserves arbitrary `ext`** (line 327) — so the *only* video-download change is detecting the extension/content-type, not the path logic.
- **The `Job` dataclass has no `parent_job_id`, no video fields, no kind.** Wave F adds them (see §4).
- **`emit()` is strict** (`vocabulary/_runtime.py` line 62): every tag and every payload key must be pre-declared in `vocabulary/versions/0.1.json` or the emit raises. New tags below must be added to that JSON (and bump considered) before they can fire. Naming follows the existing `X_REQUESTED` / `X_RECEIVED` pairing (cf. `UPSCALE_REQUESTED`/`UPSCALE_RECEIVED`).
- **MCP tools** (`mcp_server.py`) are thin `@mcp.tool()` async wrappers over `_backend.<method>` via `_run_tool`; each new bridge endpoint needs a matching backend method + MCP tool.

**Uncertainty flags carried throughout:** custom_id formats and modal IDs are MJ-internal and version-volatile (V7 default since 2025-06-17; some edit buttons were absent at V7 launch and reintroduced piecemeal — the button set on any given message is build-dependent). Video routed largely through the web app at launch and the Discord button behavior is rolling/flaky. Favorite may be an emoji **reaction**, not a component button, on the current build. Vary (Region) payload is reverse-engineered and brittle. Where a row says "verify live," capture the real interaction from desktop Discord DevTools before relying on it.

---

## 1. Master action table

`PJID` = the action sets `parent_job_id` on the child job. **All custom_ids read from the live message** unless the cell says otherwise.

| Action | Discord label | Produces | Mechanism | Proposed bridge endpoint | Proposed MCP tool | Job linkage | New vocab tags (REQUESTED / RECEIVED) | Feasibility | Caveats |
|---|---|---|---|---|---|---|---|---|---|
| **upscale (select)** | U1–U4 | single image (separated tile; carries the rich action row) | button-press (type=3) — **implemented** | existing `_ingest_message` upscale path | existing `imagine(upscale=…)` | child of grid job; `_match_upscale` keys on `Image #N` + token | (already `UPSCALE_REQUESTED`/`UPSCALE_RECEIVED`) | done | only hardcoded custom_id family; only to read uuid |
| **variation** | V1–V4 | new 2×2 grid | type=3 (Remix OFF) / type=5 (Remix ON) | `POST /action {message_id, action:"variation", slot}` | `variation(parent_job_id, slot)` | child grid, PJID | `VARIATION_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | initial-grid only; Remix-on routes to a modal (Tier 2) |
| **reroll** | loop/refresh | new 2×2 grid | type=3 (Remix OFF) / type=5 (Remix ON) | `POST /action {…, action:"reroll"}` | `reroll(parent_job_id)` | child grid, PJID | `REROLL_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | initial-grid only; Remix-on → modal |
| **upscale_subtle** | Upscale (Subtle) | single higher-res image (2×) | button-press (type=3) | `POST /action {…, action:"upscale_subtle"}` | `upscale_variant(parent_job_id, mode="subtle")` | child single image, PJID | `UPSCALE_VARIANT_REQUESTED` / `UPSCALE_VARIANT_RECEIVED` | easy press / moderate routing | post-separation only; NOT the `upsample::` family — needs new result-match (single image, token may not echo) |
| **upscale_creative** | Upscale (Creative) | single higher-res image (2×) | button-press (type=3) | `POST /action {…, action:"upscale_creative"}` | `upscale_variant(parent_job_id, mode="creative")` | child single image, PJID | `UPSCALE_VARIANT_REQUESTED` / `UPSCALE_VARIANT_RECEIVED` | easy press / moderate routing | as above; result can drift from source |
| **vary_subtle** | Vary (Subtle) | new 2×2 grid | type=3 (Remix OFF) / type=5 (ON) | `POST /action {…, action:"vary_subtle"}` | `vary(parent_job_id, mode="subtle")` | child grid, PJID | `VARY_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | recognition hint `low_variation`; Remix-on → modal |
| **vary_strong** | Vary (Strong) | new 2×2 grid | type=3 (Remix OFF) / type=5 (ON) | `POST /action {…, action:"vary_strong"}` | `vary(parent_job_id, mode="strong")` | child grid, PJID | `VARY_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | recognition hint `high_variation`; Remix-on → modal |
| **zoom_out_2x** | Zoom Out 2x | new 2×2 grid (outpaint) | button-press (type=3) | `POST /action {…, action:"zoom_out", factor:2}` | `zoom_out(parent_job_id, factor=2.0)` | child grid, PJID | `ZOOM_OUT_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | post-upscale only |
| **zoom_out_1_5x** | Zoom Out 1.5x | new 2×2 grid (outpaint) | button-press (type=3) | `POST /action {…, action:"zoom_out", factor:1.5}` | `zoom_out(parent_job_id, factor=1.5)` | child grid, PJID | `ZOOM_OUT_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | bridge picks the component whose factor matches; post-upscale only |
| **custom_zoom** | Custom Zoom | new 2×2 grid (outpaint, edited `--zoom`/`--ar`/prompt) | **modal-submit (type=5)** | `POST /action {…, action:"custom_zoom", zoom, ar?, prompt?}` | `custom_zoom(parent_job_id, zoom, ar?, prompt?)` | child grid, PJID | `CUSTOM_ZOOM_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate (Tier 2) | press returns a modal; bridge must read the *modal* custom_id + text-input custom_id from the press response and POST type=5. `--zoom 1` + `--ar` is the "zoom in"/AR-change path |
| **zoom_in** | (no confirmed discrete button) | — | unknown | — (don't add a discrete endpoint) | — | — | — | **defer / verify live** | not a confirmed labeled button in v6/v7; almost certainly Custom Zoom with low zoom. If a real button exists, it's a plain press; if part of Custom Zoom, it's Tier 2 |
| **make_square** | Make Square | new 2×2 grid (outpaint to 1:1) | button-press (type=3) | `POST /action {…, action:"make_square"}` | `make_square(parent_job_id)` | child grid, PJID | `MAKE_SQUARE_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | only present for non-square sources — bridge must tolerate absence |
| **pan_left/right/up/down** | Pan arrows | new pan grid (outpaint, often 2 wider tiles) | type=3 (Remix OFF) / type=5 (ON) | `POST /action {…, action:"pan", dir}` | `pan(parent_job_id, direction)` | child grid, PJID | `PAN_REQUESTED` / `GRID_CHILD_RECEIVED` | moderate | post-upscale only; perpendicular arrows may vanish after first pan; Remix-on → modal |
| **vary_region** | Vary (Region) / brush | new 2×2 grid (inpaint of masked area) | **modal-submit + uploaded MASK** | `POST /action {…, action:"vary_region", mask_b64, prompt?}` | `vary_region(parent_job_id, mask_b64, prompt?)` | child grid, PJID | `VARY_REGION_REQUESTED` / `GRID_CHILD_RECEIVED` | **hard / research spike (Tier 3)** | launches a web mask editor, not a text modal; submit carries a base64 PNG mask (white=repaint, black=keep, same WxH) + origin uuid (+ Remix prompt). Payload reverse-engineered, version-volatile, not in erictik/midjourney-api (issue #223). Capture a live submit from DevTools first |
| **animate_low** | Animate (Low Motion) | **VIDEO (.mp4)** | button-press (type=3); result is video | `POST /action {…, action:"animate", motion:"low"}` | `animate(parent_job_id, motion="low")` | child **video** job, PJID | `ANIMATE_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 3) | result is MP4 not PNG — new download/detect branch; routing should match the MJ uuid carried in the result message components (token may not echo); ~480p raw; web-routing/rollout uncertainty — verify live |
| **animate_high** | Animate (High Motion) | **VIDEO (.mp4)** | button-press (type=3); result is video | `POST /action {…, action:"animate", motion:"high"}` | `animate(parent_job_id, motion="high")` | child **video** job, PJID | `ANIMATE_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 3) | same as low; select high vs low by matching label/custom_id read at runtime — discover, don't assume |
| **animate_manual** | Animate Manually | **VIDEO (.mp4)** | **modal-submit (type=5)** + video result | `POST /action {…, action:"animate", motion:"manual", prompt}` | `animate(parent_job_id, motion="manual", prompt)` | child **video** job, PJID | `ANIMATE_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 2+3) | needs both the modal path AND the video pipeline |
| **video_upscale** | (virtual upscale on video msg) | higher-quality **.mp4** | button-press (type=3) on the video message | `POST /action {…, action:"video_upscale"}` | `video_upscale(video_job_id)` | child video job, PJID | `VIDEO_UPSCALE_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 3) | only exists after an animate result; needs video-job state persisted first |
| **extend (auto)** | Extend / Extend Auto | longer **.mp4** (+~4s, ≤4×) | button-press (type=3) on video message | `POST /action {…, action:"extend"}` | `extend(video_job_id)` | child video job, PJID | `VIDEO_EXTEND_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 3) | buttons live on the video result message → requires video-job state to exist first |
| **extend (manual)** | Extend Manual | longer **.mp4** | **modal-submit (type=5)** | `POST /action {…, action:"extend", prompt}` | `extend(video_job_id, prompt)` | child video job, PJID | `VIDEO_EXTEND_REQUESTED` / `VIDEO_RECEIVED` | hard (Tier 2+3) | new motion prompt; depends on Remix mode |
| **favorite** | Favorite (heart) / Like | state toggle (gallery flag) | **button-press OR emoji reaction — version-dependent** | `POST /favorite {message_id}` | `favorite(job_id_or_message_id)` | none (fire-and-forget; no child, no download) | `FAVORITE_REQUESTED` / *(no RECEIVED — nothing to download)* | easy-if-button / moderate-if-reaction | inspect live message: if a Favorite **component** with a custom_id is present, press via `_press_button`; else fall back to `add_reaction(❤)` — a **different** Discord API call (`PUT /channels/{cid}/messages/{mid}/reactions/{emoji}/@me`), NOT the press path. No completion semantics |
| **see_on_web** | Web / "see it on web" | navigates browser to gallery URL | **link button (style=5) — no custom_id** | (none — harvest URL) | surfaced on `status` as `job.web_url` | none | *(none)* | **defer** | cannot be "pressed" (Discord rejects component interactions for link buttons). Useful move: read the component's `url` and record `job.web_url`. No interaction to drive |

---

## 2. Tier grouping (by mechanism / required new primitive)

### Tier 1 — plain button-press, reuses the existing press-by-custom_id seam
**No new press primitive.** Each: discover the target component by matching its `custom_id`/label against a recognition hint read off the live message, then call `_press_button(message_id, that_custom_id, guild_id)` exactly as U1–U4 do. The work is **result-routing**, not pressing.

- variation (V1–V4) *(Remix OFF)*
- reroll *(Remix OFF)*
- upscale_subtle, upscale_creative
- vary_subtle, vary_strong *(Remix OFF)*
- zoom_out_2x, zoom_out_1_5x
- make_square
- pan_left / right / up / down *(Remix OFF)*
- favorite *(only if the build exposes it as a component button; otherwise → reaction, see §3)*

Within Tier 1: actions producing a **single image** (upscale subtle/creative) need a single-image result matcher; actions producing a **new grid** (variation, reroll, vary, zoom-out, make-square, pan) need a child-grid matcher (see §4). The press itself is trivial in all cases.

### Tier 2 — modal-submit actions needing a NEW primitive
**Requires a new `_submit_modal(...)` helper** mirroring `_press_button` but with interaction `type=5` and `data.components = [{type:1, components:[{type:4, custom_id:<text-input id>, value:<filled value>}]}]`. The flow: read the button's custom_id → press it (or derive the modal id by the documented prefix rewrite) → read the modal custom_id + text-input custom_id from the response → fill `value` → POST type=5. This single helper unlocks the whole tier.

- **custom_zoom** — text modal: prompt + `--zoom (1–2)` + optional `--ar`.
- **animate_manual** — prompt-edit modal (also a Tier 3 video result).
- **extend_manual** — motion-prompt modal (also Tier 3 video result).
- **Remix-ON variants** of variation / reroll / vary_strong / vary_subtle / pan — when the account has Remix mode on, these route to a prompt-edit modal instead of generating immediately. The bridge should detect this at press time (the press returns a modal rather than a result) and route through `_submit_modal`; otherwise treat them as Tier 1. **Decide Remix on/off per deployment** and document it; the same labeled button straddles Tier 1 and Tier 2 depending on that setting.

### Tier 3 — mask / video special cases (new pipelines)
- **vary_region** — mask editor. Synthesize a black/white PNG mask (same WxH as source), base64-encode, and POST the inpaint interaction carrying mask + origin uuid (+ optional Remix prompt). Reverse-engineered and brittle; **capture a live submit from DevTools before building**; not implemented in erictik/midjourney-api (issue #223). Treat as a research spike, separate track.
- **animate_low / animate_high / animate_manual / video_upscale / extend** — **VIDEO result handling.** See §3.

---

## 3. Video result handling (the load-bearing difference from PNG)

The press is ordinary; the **result is an MP4 on a new message**, which the current ingest cannot handle. Required changes:

1. **Detect video, don't assume PNG.** In `_ingest_message`, branch on `att.content_type` starting with `video/` (or `att.filename` ending `.mp4`) instead of defaulting `ext` to `.png` at lines 611/776. `_safe_output_path` already preserves arbitrary `ext`, so this is a small, localized change. Route the MP4 to a video suffix (e.g. `a.mp4` / `a_video.mp4`).
2. **Route by MJ uuid, not the prompt-echo token.** Button-triggered animate is not guaranteed to echo `cscidnocollide{token}` in the result message, so `_match_grid`'s token path may miss. Match the result by the MJ job uuid carried in the **result message's own components** — the same shape `_extract_mj_uuid` already uses. Capture the source uuid at press time and link it to the video child job.
3. **New emit pair.** `ANIMATE_REQUESTED` → `VIDEO_RECEIVED` (carry `bytes`, `path`, and the resolved `content_type`). Distinct from `GRID_RECEIVED`/`UPSCALE_RECEIVED` so the operator's signal stream shows a video landed, not a PNG.
4. **Video-job state must exist before Extend/Video-Upscale.** Extend and virtual-upscale buttons live on the **video result message**, which only exists after an animate completes. The `Job` model needs `video_message_id` + `video_mj_uuid` persisted from the animate result before those presses are addressable. So Extend/Video-Upscale are strictly downstream of a tracked animate result.
5. **Quality note:** raw animate clips are ~480p; a higher-quality MP4 requires a *second* press (`video_upscale`) on the video message → another round-trip, again discoverable from components.

**Favorite-as-reaction** is the other mechanism mismatch: if the live message exposes Favorite as a component button, press it; if it's the historical heart **emoji reaction**, the press path does not apply — use `discord.py-self`'s `Message.add_reaction` / `PUT …/reactions/{emoji}/@me`. The bridge should inspect the live message and pick the path; `favorite` has no RECEIVED tag because nothing is downloaded.

---

## 4. Bridge / data-model changes (summary)

- **`Job` additions:** `parent_job_id: str | None`, `kind: str` (`"grid" | "single" | "video"`), and for video lineage `video_message_id: int | None`, `video_mj_uuid: str | None`. Child jobs created by Tier 1/2/3 actions set `parent_job_id` and reuse the same `request_token`/`asset_id` lineage where useful.
- **One generic endpoint** `POST /action {parent_job_id, action, …params}` is preferable to ~15 endpoints: it (a) looks up the parent's `message_id`, (b) scans that message's live components, (c) selects the component whose custom_id/label matches the action's recognition hint, (d) presses (Tier 1) or modal-submits (Tier 2) or mask-submits (Tier 3), (e) registers a child job (with `parent_job_id`) into `PENDING_GRID`/a new pending-list so the existing result loop claims the result. `favorite` and `see_on_web` are exceptions (separate `/favorite`; URL-harvest only).
- **New helper:** `_submit_modal(message_id, modal_custom_id, text_input_custom_id, value, guild_id)` (type=5). Add to the Discord-side block next to `_press_button`.
- **New result matchers:** `_match_child_grid` (new grid keyed by parent uuid) and `_match_single_image` (subtle/creative result), plus the video branch in `_ingest_message`.
- **Vocabulary:** add all new tags + their declared `payload`/`optional_payload` to `vocabulary/versions/0.1.json` before any emit (strict validator will otherwise raise). New tags: `VARIATION_REQUESTED`, `REROLL_REQUESTED`, `UPSCALE_VARIANT_REQUESTED`, `UPSCALE_VARIANT_RECEIVED`, `VARY_REQUESTED`, `ZOOM_OUT_REQUESTED`, `CUSTOM_ZOOM_REQUESTED`, `MAKE_SQUARE_REQUESTED`, `PAN_REQUESTED`, `VARY_REGION_REQUESTED`, `ANIMATE_REQUESTED`, `VIDEO_RECEIVED`, `VIDEO_UPSCALE_REQUESTED`, `VIDEO_EXTEND_REQUESTED`, `GRID_CHILD_RECEIVED`, `FAVORITE_REQUESTED`. Consider a new vocab category `action` (alongside `job`/`discord`) so these group cleanly; update the parity check (`tools/check_vocabulary_parity.py`) accordingly.
- **MCP:** one `@mcp.tool()` per logical action (or a single `action(...)` tool) wrapping a `_backend` method via `_run_tool`, mirroring the existing `imagine`/`wait`/`status` pattern.

---

## 5. Recommended build order

1. **Data model + generic `/action` + child-grid routing** → unlocks all Tier 1 grid actions (variation, reroll, vary, zoom-out, make-square, pan) and single-image routing (upscale subtle/creative). Highest value, lowest risk; reuses the proven press seam.
2. **`favorite`** (component-or-reaction probe) and **`see_on_web`** URL harvest — small, independent.
3. **`_submit_modal` (type=5)** → custom_zoom, then Remix-on variants. Self-contained primitive.
4. **Video pipeline** (detect MP4, uuid-routing, `VIDEO_RECEIVED`, video-job state) → animate low/high, then video_upscale + extend(auto). Animate_manual + extend_manual sit at the Tier 2∩Tier 3 intersection (need both modal + video).
5. **vary_region** — research spike last; capture a live DevTools submit before committing code.

**Explicit reminder for implementers:** the bridge reads custom_ids from the **live message components** at action time. Do not hardcode any custom_id, modal id, or label string from this document or the cited sources — those are recognition hints for *matching* the right live component, and MJ can change them without notice. Discover, match, then press/submit.

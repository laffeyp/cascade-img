// tools/cascade-asset.ts
//
// Sprint 4.0 — Cascade asset pipeline driver.
//
// Usage:
//   npx tsx tools/cascade-asset.ts <asset_id> [--upscale all|1|2|3|4|grid]
//
// Where <asset_id> is one of:
//   bird, clue_a, clue_b, clue_c, region_forest_floor
//
// Defaults to `--upscale all` (returns four upscales per roll, lets Architect
// curate from four real candidates rather than a 2x2 grid thumbnail).
// Use `--upscale grid` for the cheapest first preview.
//
// Requires the Cascade bridge running at http://127.0.0.1:5000.
// Start it with: cd /Users/peterlaffey/Documents/Claude/Projects/Cascade/asset_pipeline && python mj_bridge.py
//
// Appends an entry to handoff/cascade-prompts/sprint-4.0.md for reproducibility.

import * as fs from "node:fs/promises";
import * as path from "node:path";

const BRIDGE = "http://127.0.0.1:5000";

const MOODBOARD = "m7458053701014388751";
const SREF_CHARACTER = "https://cdn.midjourney.com/54cefb43-412a-4931-9895-36cdb2e42a63/0_0.png";
const SREF_ENVIRONMENT = "https://cdn.midjourney.com/4afa7423-2ca6-4862-91db-f8bb4447af8b/0_3.jpeg";

// Omni-reference: single-image CDN URL of the curated bird sprite
// (assets/bird.png uploaded to the MJ channel). A single-image oref locks
// MJ onto ONE bird rather than extracting averaged identity from a 2×2
// grid of variants — eliminates the "different birds flickering" drift.
// Used with --ow 400 for tight identity match (default 100 was too loose).
const OREF_BIRD = "https://cdn.discordapp.com/attachments/1502243953687265485/1508801075270914118/bird.png";

type AssetSpec = {
  subject: string;
  sref: "character" | "environment";
  ar: "1:1" | "16:9";
  oref?: string;  // optional omni-reference URL (V7's identity lock)
  ow?: number;    // omni weight 0-1000 (100 default; only used if oref set)
};

// Subjects bake in the sprite-art aesthetic per katybird-combined-spec.md §6.1–§6.3
// and voice-tone-canon.md ("simple 2D sprite art... handmade, readable, restrained";
// "limited palettes, readable silhouettes, expressive but minimal"). The character
// sref alone doesn't dominate on small natural objects (feathers etc) and MJ falls
// back to photorealism — explicit "pixel-art sprite" / "low-resolution game sprite"
// language pins it down. Sref weight `::2` pushes MJ harder toward the locked style;
// `--s 50` reduces default stylize so the sref drives instead of MJ's prettifier.
const ASSETS: Record<string, AssetSpec> = {
  bird: {
    subject:
      "pixel-art sprite of a small finch, side view, plump and round, idle pose, low-resolution 2D game sprite, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  clue_a: {
    subject:
      "pixel-art sprite of a single wet feather, small 2D game item icon, low-resolution sprite art, limited palette, handmade restrained, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  clue_b: {
    subject:
      "pixel-art sprite of fresh scratch marks on a small slab of tree bark, small 2D game item icon, low-resolution sprite art, limited palette, handmade restrained, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  clue_c: {
    subject:
      "pixel-art sprite of a small keepsake left behind on the forest floor, a tiny trinket, 2D game item icon, low-resolution sprite art, limited palette, handmade restrained, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  region_forest_floor: {
    subject:
      "pixel-art sprite background of a quiet forest floor at low light, 2D sprite-game environment, late-afternoon melancholy, restrained limited palette, handmade readable composition, no characters, 16:9 composed scene",
    sref: "environment",
    ar: "16:9",
  },

  // ----- Phase 4.5: Wave-3 region panels -----
  // Three sibling backdrops to region_forest_floor — same prompt, same sref,
  // same moodboard. Variation comes from MJ's natural roll-to-roll spread.
  // These sit side-by-side with region_forest_floor at x=1456/2912/4368 in
  // WorldScene; together they form a 5824-wide continuous forest the player
  // walks left-to-right through, one clue per panel.
  region_forest_a: {
    subject:
      "pixel-art sprite background of a quiet forest floor at low light, 2D sprite-game environment, late-afternoon melancholy, restrained limited palette, handmade readable composition, no characters, 16:9 composed scene",
    sref: "environment",
    ar: "16:9",
  },
  region_forest_b: {
    subject:
      "pixel-art sprite background of a quiet forest floor at low light, 2D sprite-game environment, late-afternoon melancholy, restrained limited palette, handmade readable composition, no characters, 16:9 composed scene",
    sref: "environment",
    ar: "16:9",
  },
  region_forest_c: {
    subject:
      "pixel-art sprite background of a quiet forest floor at low light, 2D sprite-game environment, late-afternoon melancholy, restrained limited palette, handmade readable composition, no characters, 16:9 composed scene",
    sref: "environment",
    ar: "16:9",
  },

  // Phase 4.6 — Katy reveal panel. Same forest, same time of day, same
  // palette as the other panels, BUT with light rain falling. The rain
  // marks this as the closing scene without breaking the visual continuity
  // of the four-panel forest the player just walked through.
  region_forest_rain: {
    subject:
      "pixel-art sprite background of a quiet forest floor at low light, light rain falling steadily, wet ground reflecting, 2D sprite-game environment, late-afternoon melancholy, restrained limited palette, handmade readable composition, no characters, 16:9 composed scene",
    sref: "environment",
    ar: "16:9",
  },

  // ----- Wave 2: apology HUD glyphs -----
  // Per Combined Spec §4.7 — four-slot apology composition. Visual goal: small
  // iconic glyphs, abstract enough to read at HUD size (~16-32px), tonally
  // consistent with the sprite-art aesthetic. Character sref kept for stylistic
  // coherence with the rest of the asset set; subject leans abstract-icon.
  glyph_surface_action: {
    subject:
      "pixel-art icon of a single small footprint or footstep mark, abstract minimalist sprite icon, small 2D game UI glyph, simple readable silhouette, limited muted palette, handmade restrained, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  glyph_recognized_pattern: {
    subject:
      "pixel-art icon of two mirrored shapes meeting, abstract minimalist sprite icon symbolizing pattern recognition, small 2D game UI glyph, simple readable silhouette, limited muted palette, handmade restrained, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  glyph_recognized_wound: {
    subject:
      "pixel-art icon of a small broken twig with a faint tear shape, abstract minimalist sprite icon symbolizing acknowledged hurt, small 2D game UI glyph, simple readable silhouette, limited muted palette, handmade restrained, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  glyph_specific_repair: {
    subject:
      "pixel-art icon of a small tied knot or mended thread, abstract minimalist sprite icon symbolizing a concrete repair, small 2D game UI glyph, simple readable silhouette, limited muted palette, handmade restrained, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },

  // ----- Wave 2: Katy forms -----
  // Per Combined Spec §2.3 / §12.5 — Katy is sparse, indirect, glimpsed.
  // Three forms cover the KATY_GLIMPSED payload values.
  katy_silhouette: {
    subject:
      "pixel-art sprite silhouette of a very small finch, side view from behind, just shape no facial detail, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  katy_movement: {
    subject:
      "pixel-art sprite of a small finch mid-motion blur, wing-flick suggestion only, fleeting partial glimpse, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },
  katy_direct_sighting: {
    subject:
      "pixel-art sprite of a small juvenile finch, side view, smaller and younger than the brother finch, plump and round, idle pose, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
  },

  // ----- Sprint 4.7: bird flit-flap animation frames -----
  // Three wing positions for the flit arc. Cycled during the tween's
  // onUpdate to read as flapping. SAME bird as `assets/bird.png` —
  // identity locked via --cref CREF_BIRD --cw 100. Only the wings vary.
  bird_wing_up: {
    subject:
      "the same finch in SIDE VIEW facing LEFT (matching the reference orientation), wings raised UP in a full upstroke, mid-flap, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },
  bird_wing_mid: {
    subject:
      "the same finch in SIDE VIEW facing LEFT (matching the reference orientation), wing extended outward horizontally, mid-flap, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },
  bird_wing_down: {
    subject:
      "the same finch in SIDE VIEW facing LEFT (matching the reference orientation), wing folded DOWN against its body at the bottom of a downstroke, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, readable silhouette, centered, transparent background",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },

  // ----- Sprint 4.7d: wings-ONLY overlay sprites -----
  // Body stays locked to assets/bird.png; only the wings overlay swaps
  // during flit. These prompts ask MJ to produce a wing on its own,
  // floating against transparent background, no bird body visible.
  // Identity-locked to canonical bird via oref + ow=1000 so the wing
  // style and palette match.
  wing_only_up: {
    subject:
      "ONLY a single small finch's wing in full UPSTROKE position (raised up), isolated against transparent background, NO bird body visible, NO head, NO feet, NO eyes, just the wing alone in the air, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, side view",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },
  wing_only_mid: {
    subject:
      "ONLY a single small finch's wing in MID-FLAP position (extended horizontally), isolated against transparent background, NO bird body visible, NO head, NO feet, NO eyes, just the wing alone, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, side view",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },
  wing_only_down: {
    subject:
      "ONLY a single small finch's wing in DOWNSTROKE position (angled down), isolated against transparent background, NO bird body visible, NO head, NO feet, NO eyes, just the wing alone, small 2D game sprite, low-resolution, limited palette, handmade restrained sprite art, side view",
    sref: "character",
    ar: "1:1",
    oref: OREF_BIRD,
    ow: 1000,
  },
};

function buildPrompt(spec: AssetSpec): string {
  const srefUrl = spec.sref === "character" ? SREF_CHARACTER : SREF_ENVIRONMENT;
  let prompt = `${spec.subject} --ar ${spec.ar} --v 7 --style raw --p ${MOODBOARD} --sref ${srefUrl}`;
  if (spec.oref) {
    prompt += ` --oref ${spec.oref} --ow ${spec.ow ?? 100}`;
  }
  return prompt;
}

type ImagineResponse = {
  job_id: string;
  asset_id: string;
  status: string;
  upscale: number | string | null;
};

type JobRecord = {
  job_id: string;
  asset_id: string;
  status: string;
  progress?: string;
  image_path?: string | null;
  grid_path?: string | null;
  upscale_paths?: Record<string, string>;
  upscale_pending?: string[];
  error?: string | null;
};

async function postImagine(
  prompt: string,
  assetId: string,
  upscale: "all" | number | null
): Promise<ImagineResponse> {
  const body: Record<string, unknown> = { prompt, asset_id: assetId };
  if (upscale !== null) body.upscale = upscale;
  const res = await fetch(`${BRIDGE}/imagine`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`/imagine failed: ${res.status} ${text}`);
  }
  return (await res.json()) as ImagineResponse;
}

async function waitJob(jobId: string, timeoutSec: number): Promise<JobRecord> {
  const res = await fetch(`${BRIDGE}/wait/${jobId}?timeout=${timeoutSec}`);
  if (res.status === 504) {
    throw new Error(`/wait timed out after ${timeoutSec}s for job ${jobId}`);
  }
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`/wait failed: ${res.status} ${text}`);
  }
  return (await res.json()) as JobRecord;
}

async function checkHealth(): Promise<void> {
  let res: Response;
  try {
    res = await fetch(`${BRIDGE}/health`);
  } catch (e) {
    throw new Error(
      `Cannot reach Cascade bridge at ${BRIDGE}. Start it with:\n  cd /Users/peterlaffey/Documents/Claude/Projects/Cascade/asset_pipeline && python mj_bridge.py`
    );
  }
  if (!res.ok) throw new Error(`/health returned ${res.status}`);
  const h = (await res.json()) as { discord_ready: boolean; output_dir: string };
  if (!h.discord_ready) {
    throw new Error(
      "Cascade bridge is up but Discord is not connected yet. Wait for 'Discord connected as <you>' in the bridge log, then retry."
    );
  }
  console.log(`[cascade] bridge healthy, output_dir=${h.output_dir}`);
}

async function logPrompt(
  assetId: string,
  prompt: string,
  upscale: "all" | number | null,
  job: JobRecord
): Promise<void> {
  const logPath = path.resolve(
    process.cwd(),
    "handoff/cascade-prompts/sprint-4.0.md"
  );
  await fs.mkdir(path.dirname(logPath), { recursive: true });
  let header = "";
  try {
    await fs.access(logPath);
  } catch {
    header =
      "# Sprint 4.0 — Cascade prompt log\n\n*Append-only. One block per roll. Reproducibility ledger for Wave-1 visual assets.*\n\n";
  }
  const now = new Date().toISOString();
  const block = [
    `## ${now} — ${assetId} (upscale=${upscale ?? "grid"})`,
    "",
    "Prompt:",
    "```",
    prompt,
    "```",
    "",
    `Job: \`${job.job_id}\` — status=${job.status}`,
    job.image_path ? `Image: \`${job.image_path}\`` : null,
    job.grid_path ? `Grid: \`${job.grid_path}\`` : null,
    job.upscale_paths && Object.keys(job.upscale_paths).length
      ? `Upscales: ${Object.entries(job.upscale_paths)
          .map(([k, v]) => `u${k}=\`${v}\``)
          .join(", ")}`
      : null,
    job.error ? `Error: ${job.error}` : null,
    "",
    "---",
    "",
  ]
    .filter((l) => l !== null)
    .join("\n");
  await fs.appendFile(logPath, header + block, "utf8");
}

function parseUpscaleFlag(argv: string[]): "all" | number | null {
  // Default: grid-only. Upscales add complexity (button-press dance, longer
  // wait, MJ component-layout fragility) and Wave-1 curation works fine from
  // the 2x2 grid. Pass --upscale 1|2|3|4|all to opt in.
  const idx = argv.indexOf("--upscale");
  if (idx === -1) return null;
  const v = argv[idx + 1];
  if (v === "all") return "all";
  if (v === "grid") return null;
  const n = Number(v);
  if (n >= 1 && n <= 4) return n;
  throw new Error(`--upscale must be all|grid|1|2|3|4 (got ${v})`);
}

async function main(): Promise<void> {
  const args = process.argv.slice(2);
  const assetId = args[0];
  if (!assetId || !(assetId in ASSETS)) {
    console.error(
      `usage: npx tsx tools/cascade-asset.ts <asset_id> [--upscale all|grid|1|2|3|4]\n  asset_id must be one of: ${Object.keys(
        ASSETS
      ).join(", ")}`
    );
    process.exit(2);
  }
  const upscale = parseUpscaleFlag(args);

  await checkHealth();

  const spec = ASSETS[assetId]!;
  const prompt = buildPrompt(spec);
  console.log(`[cascade] asset_id=${assetId} upscale=${upscale ?? "grid"}`);
  console.log(`[cascade] prompt: ${prompt}`);

  const submit = await postImagine(prompt, assetId, upscale);
  console.log(`[cascade] submitted job_id=${submit.job_id}`);

  // 600s = 10 min. --upscale all is grid + 4 upscales which can take 5-8 min
  // on MJ fast mode; --upscale 1..4 needs ~3-5 min; grid-only fits in 180s.
  const waitTimeout = upscale === "all" ? 600 : upscale === null ? 180 : 360;
  console.log(`[cascade] waiting up to ${waitTimeout}s for completion...`);
  const job = await waitJob(submit.job_id, waitTimeout);

  if (job.status === "failed") {
    console.error(`[cascade] FAILED: ${job.error ?? "(no error message)"}`);
    await logPrompt(assetId, prompt, upscale, job);
    process.exit(1);
  }

  console.log(`[cascade] DONE status=${job.status}`);
  if (job.image_path) console.log(`[cascade] image: ${job.image_path}`);
  if (job.grid_path) console.log(`[cascade] grid:  ${job.grid_path}`);
  if (job.upscale_paths) {
    for (const [k, v] of Object.entries(job.upscale_paths)) {
      console.log(`[cascade] u${k}:    ${v}`);
    }
  }

  await logPrompt(assetId, prompt, upscale, job);
  console.log(`[cascade] logged to handoff/cascade-prompts/sprint-4.0.md`);
}

void main().catch((e) => {
  console.error(`[cascade] ${(e as Error).message}`);
  process.exit(1);
});

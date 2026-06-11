# vocabulary

The JSON file in this directory is a versioned catalog of the named events cascade-img emits at runtime, with the payload fields each one carries. Events come from the daemon, CLI, and MCP server.

## What's in the catalog

Each entry is a tag name (for example `IMAGINE_FIRED`) plus the payload fields it carries (`asset_id`, `job_id`, ...). The catalog also records which event sequences are valid and which entities each tag refers to.

At runtime, the package validates every event against this catalog. An unknown tag raises; a missing required field raises.

## How to read and use it

`0.1.json` is the current catalog. For a readable per-tag listing (payload fields, emitter, allowed values, when it fires), see [`0.1-reference.md`](0.1-reference.md) — generated from the JSON, kept fresh by CI. [`0.1-context.md`](0.1-context.md) explains how the events fit together: the happy-path sequence, the error codes, and which artifact each tag corresponds to.

## How to extend

Add a new tag entry to `0.1.json` (and the identical package-data copy under `packages/python/src/cascade_img/vocabulary/versions/`) before any callsite that emits that tag, then regenerate the reference with `python3 packages/python/tools/render_vocabulary_reference.py`. The parity check (`packages/python/tools/check_vocabulary_parity.py`) walks the source tree and fails if any callsite references an undeclared tag.

`0.1` is locked: existing tags are frozen (no renames, removals, or payload changes), but new tags may still be added. Because this is pre-1.0, that additive growth lands **in-place** in `0.1` — a new tag is appended to the same catalog rather than minting a new version (the catalog has grown 27 → 47 → 48 this way); the lock binds only renames, removals, and semantic or payload changes to tags that already shipped. Those breaking changes bump to `0.2`, where removals are deprecation entries, not deletes.

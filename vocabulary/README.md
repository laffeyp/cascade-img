# vocabulary

The JSON file in this directory is a versioned catalog of the named events cascade-img emits at runtime, with the payload fields each one carries. Events come from the daemon, CLI, and MCP server.

## What's in the catalog

Each entry is a tag name (for example `IMAGINE_FIRED`) plus the payload fields it carries (`asset_id`, `job_id`, ...). The catalog also records which event sequences are valid and which entities each tag refers to.

At runtime, the package validates every event against this catalog. An unknown tag raises; a missing required field raises.

## How to read and use it

`0.1.json` is the current catalog. Open it to see the full list of tags and their payloads. To find what a given operation emits, look up its tag.

## How to extend

Add a new tag entry to `0.1.json` before any callsite that emits that tag. The parity check (`packages/python/tools/check_vocabulary_parity.py`) walks the source tree and fails if any callsite references an undeclared tag.

Once `0.1` is locked, structural changes bump to `0.2`. Backwards-incompatible removals are deprecation entries, not deletes.

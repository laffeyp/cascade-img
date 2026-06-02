# vocabulary

The JSON file in this directory is the catalog of named events cascade-img emits at runtime — every state transition the daemon, CLI, and MCP server produce, with the payload fields each one carries.

## What this is for

cascade-img is designed for LLM operators. An agent driving the tool reads structured events (`IMAGINE_FIRED { asset_id, job_id, ... }`) instead of parsing log prose. When something goes wrong, the agent reads the captured event sequence and decides what to do; it doesn't need a human to translate.

For this to work, the events have to be stable: the tag names, the payload fields, and the meaning behind them can't drift between sessions or releases. The catalog in this directory is that contract.

At runtime, every `emit("TAG", ...)` call is validated against this catalog. Unknown tag → raises. Missing required field → raises. The catalog also documents how each event slots into a wider grammar: which entities exist, which event sequences are valid, what evidence each tag's payload must carry. That structure is optional to consult and required to honor.

## Why call it vocabulary

This is an experimental approach to designing software for LLM operators — the idea being that a program with a stable, typed, documented event grammar is legible to an LLM in a way that ordinary log output isn't. "Vocabulary" names the catalog itself: the limited set of things the program knows how to say.

## How to extend

Add a new tag entry to `0.1.json` before any `emit("NEW_TAG", ...)` callsite. The parity check (`packages/engine/tools/check_vocabulary_parity.py`) walks the source tree and fails if any callsite references an undeclared tag.

Once `0.1` is locked, structural changes bump to `0.2`. Backwards-incompatible removals are deprecation entries, not deletes.

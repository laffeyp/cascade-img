# Contributing

cascade-img is a small project. Contributions are welcome; the rules are short.

## The priority rule

**LLM operators are the primary user.** Contributions that optimize for human-developer ergonomics at the expense of LLM-operator ergonomics will be declined. Concrete consequences:

- Output paths are deterministic and predictable. A new feature that introduces a timestamp suffix or a UUID in a returned path is the wrong shape.
- Errors carry remediation, not blame. A new failure mode that raises a bare exception without a stable `code` and a `remediation` pointing at RUNBOOK.md is incomplete.
- The CLI's `--json` (or default JSON output) emits a single structured object on stdout. Stderr is reserved for human-readable progress. A new subcommand that prints prose to stdout breaks LLM parsers.
- New MCP tools include input schemas derived from typed signatures and follow the `{ok, result | error: {code, message, remediation?}}` envelope.
- Working-memory primitives (the prompt log especially) are append-only and structured. A new log format that returns markdown text from `read_prompt_log` is the wrong shape — `render_markdown` is a separate, optional view.

## Dev environment

```bash
git clone https://github.com/greenrosesystems/cascade-img.git
cd cascade-img/packages/engine
pip install -e '.[dev]'      # editable install + ruff + pytest + mypy
```

The four gates each commit must pass (run from `packages/engine/`):

```bash
ruff check .                                 # lint
pytest                                       # unit tests
python3 tools/check_vocabulary_parity.py     # every emit() uses a declared tag
diff ../../vocabulary/0.1.json src/cascade_img/vocabulary/versions/0.1.json   # mirror in sync
```

## Structured-event discipline

Every important state change emits a vocabulary tag. The vocabulary is locked at `packages/engine/src/cascade_img/vocabulary/versions/0.1.json` (with a byte-identical mirror at `vocabulary/0.1.json` at the repo root). Workflow for a code change that introduces a new state transition:

1. Identify the new state transitions the change introduces.
2. Add the new tags to the vocabulary JSON with `payload`, `category`, `stratum`, and a `note` field. Mirror the change to the repo-root copy.
3. Add the `emit(...)` callsites.
4. Run the parity tool: `python3 tools/check_vocabulary_parity.py`.
5. Add behavior-contract tests that assert both the function output AND the emitted event sequence.
6. Run the full suite: `pytest`.

Vocabulary changes are treated as breaking — minor bump on the package version. Don't drop or rename existing tags without a deprecation note.

## Coding conventions

- Python 3.10+. Type annotations on every public function. `from __future__ import annotations` at the top of every module.
- No emojis in any committed file (including this one) unless the maintainer explicitly requests them.
- No "made with AI" footers in commits, PRs, or generated artifacts.
- `ruff check .` for lint, `ruff format .` for format. Both configured in `pyproject.toml`.
- One concern per PR; every commit's diff leaves the test suite passing.

## What's in scope

- Bug fixes against the bridge daemon's Discord interaction handling.
- New backend implementations conforming to `ImageGenerationBackend`.
- New curation utilities (e.g. better alpha-key heuristics, atlas packing).
- Documentation improvements that surface operational lessons.
- New entries under `examples/<consumer>/` — worked examples of one project's usage, not generic prompt templates. (Package-shipped prompts are not in scope; AGENTS.md is the canonical operator guide.)

## What's out of scope at v0.1

- Web UI. cascade-img is a library, a CLI, and an MCP server. A web UI is a separate project.
- Hosted SaaS. Runs locally; user owns the Discord account, keys, prompts, and ToS exposure.
- Audio/video generation. Image only. Other media get separate packages under the Green Rose Systems org.
- LoRA / fine-tuning. Upstream of generation; not the cascade layer.

## Reporting bugs

Open an issue at [github.com/greenrosesystems/cascade-img/issues](https://github.com/greenrosesystems/cascade-img/issues). Include:

- The structured error payload (code, message, remediation).
- The output of `cascade-mj-bridge --doctor`.
- A minimal reproducer if possible (a dry-run usually suffices for compose/log issues; live-fire issues need the operational context).

## License

By contributing you agree your contribution is licensed under the MIT License.

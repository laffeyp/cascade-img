# Contributing

cascade-img is a small project and contributions are welcome.

## Setup

```bash
git clone https://github.com/greenrosesystems/cascade-img.git
cd cascade-img/packages/python
pip install -e '.[dev]'
```

Run the checks before opening a PR (from `packages/python/`):

```bash
ruff check . && ruff format --check . && mypy src/cascade_img && pytest
```

`pytest` skips the live Discord/Midjourney tier by default, so you don't need
credentials. To run the live end-to-end walk (fires a real `/imagine`):

```bash
CASCADE_LIVE=1 CASCADE_ENV_FILE=/path/to/.env pytest -m e2e
```

## A few conventions

- Python 3.10+, type annotations on public functions, `from __future__ import
  annotations` at the top of each module.
- cascade-img is built to be driven by LLM agents, so keep tool outputs
  structured and deterministic (the `{ok, result | error}` envelope, stable
  error codes). See [AGENTS.md](./AGENTS.md).
- One concern per PR; keep the suite green.

## Bugs

Open an issue with the structured error payload and, for live-fire issues, the
output of `cascade-mj-bridge --doctor`.

## License

By contributing you agree your contribution is licensed under the MIT License.

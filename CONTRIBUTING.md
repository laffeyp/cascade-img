# Contributing

Contributions welcome. From `packages/python/`:

```bash
pip install -e '.[dev]'
ruff check . && ruff format --check . && mypy src/cascade_img && pytest
```

`pytest` skips the live Discord/Midjourney tier by default, so no credentials are needed. Target Python 3.14; keep `ruff`, `mypy`, and the suite green; one concern per PR. Bugs: open an issue with the structured error payload (plus `cascade-mj-bridge --doctor` output for live-fire issues).

By contributing you agree your contribution is licensed under Apache-2.0.

# cascade-img

An image-generation pipeline an LLM can drive. It runs Midjourney through Discord today; Flux, DALL-E, and Imagen will use the same interface later. An agent composes the prompt from reusable parts, generates, crops and optionally alpha-keys the result, and logs what it tried — through a CLI or an MCP server, with no human needed on every attempt.

```bash
git clone https://github.com/laffeyp/cascade-img
cd cascade-img/packages/python
pip install -e .
```

Three console scripts land on your `PATH`:

- `cascade-mj-bridge` — the long-running daemon that drives Midjourney via a Discord user account
- `cascade-mcp` — an MCP server that exposes the pipeline to Claude Desktop, Cursor, Cline, or any MCP-aware host
- `cascade-mj` — the CLI that composes a prompt from a registry asset, fires the generation, waits, and logs the result

Full documentation, setup procedure, failure-mode catalog, and the agent-operator guide live in the [project repository](https://github.com/laffeyp/cascade-img).

## License

Apache-2.0.

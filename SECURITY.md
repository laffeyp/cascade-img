# Security Policy

cascade-img persists a Discord user-account token in the operator's `.env` file. That token grants full account access — anyone holding it can read every message and join every server the account belongs to. The threat model and the disclosure procedure both flow from that fact.

## Reporting a vulnerability

**Do not file a public GitHub issue.** Send a private disclosure to `security@greenrosesystems.com` (PGP key available on request).

Include: a description of the vulnerability, the version (`pip show cascade-img`) and platform, the conditions required to trigger it, and any proof-of-concept that exercises it without harming a third party. Expect an acknowledgement within 72 hours and a fix or written response within 30 days for confirmed issues.

If you'd prefer a different channel, opening a GitHub Security Advisory at https://github.com/greenrosesystems/cascade-img/security/advisories/new also works.

## Scope

In scope:

- Vulnerabilities in `cascade_img/` source code (the published package).
- Vulnerabilities in the published console scripts (`cascade-mj-bridge`, `cascade-mcp`, `cascade-mj`).
- Supply-chain issues: tampered releases, compromised package metadata.
- Token-handling regressions: any code path that logs, persists, or transmits `DISCORD_USER_TOKEN` outside the channels documented below.

Out of scope:

- Vulnerabilities in upstream dependencies (`discord.py-self`, `flask`, `requests`, `Pillow`, `mcp`) — report those upstream. We will pin or patch in response to an upstream advisory.
- Discord and Midjourney's own policies. cascade-img driving a user account violates both services' Terms of Service; that's documented in `TOS.md` and is not a vulnerability in the code.
- The operator's own account compromise resulting from running cascade-img on a shared or untrusted machine.

## How the token is handled in the published code

- `DISCORD_USER_TOKEN` is read once at daemon startup via `python-dotenv`, held in `Config.discord_token`, and used as the `Authorization` header on Discord interaction calls. It is never written back to disk by the daemon.
- The daemon's `--check-env` and `--doctor` outputs report only `discord_token_present` (bool) and `discord_token_len` (int), never the token itself.
- The daemon's logs (`cascade_img.bridge` logger) do not emit the token value at any level. Test suite `test_config.py` includes a contract that asserts the token never appears in the `--check-env` JSON payload.
- The vocabulary catalog has no event tag whose payload would carry the token.

If you find a code path that violates any of the above, please report it through the disclosure channel.

## Token rotation

If a token is exposed (committed to a repository, posted to a chat, captured in a screenshot):

1. Change the Discord account password. Discord invalidates all existing tokens on password change; the leaked token becomes useless.
2. Capture a fresh token by the same procedure used initially (see `OPERATIONS.md`).
3. Update `.env` and restart the bridge.

The daemon does not store the token outside the process's memory, so no in-package state needs to be cleared.

## Supported versions

Security fixes are issued for the current minor version (`0.1.x` at present) and the immediately previous minor once one ships. Older versions receive critical-severity fixes only at the maintainer's discretion.

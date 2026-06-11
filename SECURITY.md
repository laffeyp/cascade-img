# Security

cascade-img holds a Discord user-account token (in your `.env`) that grants full account access — that's the thing worth protecting. The published code reads it once at startup, never logs it, and never writes it back to disk.

**Report a vulnerability** privately: email `security@greenrosesystems.com`, or open a [GitHub Security Advisory](https://github.com/greenrosesystems/cascade-img/security/advisories/new). Please don't file a public issue. Expect an acknowledgement within a few days.

If a token leaks, change your Discord password (that invalidates every token) and re-capture per [RUNBOOK.md](./RUNBOOK.md).

Out of scope: Discord's and Midjourney's own Terms of Service (see [TOS.md](./TOS.md)), and vulnerabilities in upstream dependencies (report those upstream).

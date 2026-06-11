# Security

cascade-img holds a Discord user-account token (in your `.env`) that grants full account access — that's the thing worth protecting. The published code reads it once at startup, never logs it, and never writes it back to disk.

**Report a vulnerability** privately: email `security@greenrosesystems.com`, or open a [GitHub Security Advisory](https://github.com/greenrosesystems/cascade-img/security/advisories/new). Please don't file a public issue. Expect an acknowledgement within a few days.

If a token leaks, change your Discord password (that invalidates every token) and re-capture per [RUNBOOK.md](./RUNBOOK.md).

The bridge daemon's HTTP API is **unauthenticated on loopback by design** — its trust boundary is "same machine". Anything that can reach the port can submit jobs on your Midjourney subscription. Don't bind it to a non-loopback interface or port-forward it without putting authentication (a reverse proxy or an SSH tunnel) in front.

Out of scope: Discord's and Midjourney's own Terms of Service (see [TOS.md](./TOS.md)), and vulnerabilities in upstream dependencies (report those upstream).

# Security

The thing worth protecting is your Discord user-account token (in `.env`), which grants full account access. cascade-img reads it once at startup, never logs it, and never writes it back to disk.

**Report a vulnerability** privately via a [GitHub Security Advisory](https://github.com/laffeyp/cascade-img/security/advisories/new) — please don't open a public issue. Expect an acknowledgement within a few days.

If a token leaks, change your Discord password (that invalidates every token) and re-capture per [RUNBOOK.md](./RUNBOOK.md).

The bridge daemon's HTTP API is **unauthenticated on loopback by design** — its trust boundary is "same machine." Anything that can reach the port can submit jobs on your Midjourney subscription, so don't bind it to a non-loopback interface or port-forward it without authentication (a reverse proxy or SSH tunnel) in front.

Out of scope: the upstream services' own terms, and vulnerabilities in dependencies (report those upstream).

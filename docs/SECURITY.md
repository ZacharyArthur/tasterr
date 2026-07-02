# Security Engineering Guide

**Living document** — unlike PRD/SPEC, this is maintained as the code evolves.
[AGENTS.md](../AGENTS.md) points here; every OpenSpec change's `design.md` must answer the
relevant checklists below (enforced via `openspec/config.yaml` rules).

> Scope: how we write secure code day-to-day. A vulnerability *reporting* policy
> (root `SECURITY.md`, GitHub convention) is a separate file added when the repo goes public.

## Threat model in 30 seconds

- **Exposure:** LAN today, internet via Cloudflare tunnel tomorrow. Write every endpoint as
  if it's already internet-facing.
- **What we protect:** TMDB/Seerr API keys, the Seerr internal URL, per-user Plex tokens and
  Seerr session cookies, Tasterr session tokens, and household viewing behavior (privacy).
- **Adversaries:** internet scanners hitting exposed endpoints; a malicious or compromised
  browser inside the household; XSS smuggled through third-party metadata (TMDB text is
  untrusted input); supply-chain compromise of a dependency.
- **Explicitly not defended:** an attacker with shell/file access to the host — they own the
  SQLite file and the env. (Encryption-at-rest for Plex tokens raises the bar, not a wall.)

## Non-negotiables (mechanically enforced)

1. Secrets never reach the client — `PublicConfig` regression test.
2. Only `clients/` performs outbound HTTP — import-linter contract.
3. Session tokens stored **hashed**; Plex tokens **encrypted** at rest.
4. Lockfiles committed; `just audit` before releases.

## Checklists by area

### Any new or changed API endpoint

- [ ] Auth dependency present (session or admin) — **default-deny**; an unauthenticated
      endpoint is an explicit, justified decision in design.md.
- [ ] Mutations: CSRF origin check + rate limit applied.
- [ ] Input validated through Pydantic models — no raw dict/query passthrough.
- [ ] Explicit `response_model` — never return ORM objects or upstream JSON unfiltered.
- [ ] Errors to the client carry no stack traces, internal URLs, or upstream error bodies.
- [ ] Logs carry no tokens, cookies, credentials, or PII.

### Auth & session code

- [ ] Credentials are forwarded to Seerr, never stored, never logged.
- [ ] Token comparisons are constant-time (compare hashes, `secrets.compare_digest`).
- [ ] Fresh session token on every login (no fixation); logout deletes the row.
- [ ] Cookie flags: `HttpOnly`, `SameSite=Lax`, `Secure` behind HTTPS.
- [ ] Auth endpoints rate-limited tightly; failures are generic (no user enumeration).

### Outbound HTTP (`clients/`)

- [ ] Base URLs come from validated settings only — never from user input (SSRF).
- [ ] Every call has a timeout; retries are bounded.
- [ ] Browser headers are not forwarded upstream; upstream headers are not returned downstream.
- [ ] Upstream JSON is untrusted: parse into typed models, drop unknown fields.

### Frontend

- [ ] No `dangerouslySetInnerHTML`; render TMDB/Seerr text as text, always.
- [ ] External URLs (Seerr redirect, Plex deep links) come from the BFF — never assembled
      client-side from data.
- [ ] No tokens or secrets in `localStorage`/`sessionStorage`; the session lives in the
      HttpOnly cookie the JS can't read.

### Database & migrations

- [ ] SQLAlchemy expressions only — no string-built SQL, ever.
- [ ] New columns holding tokens/secrets: encrypted (Fernet) and justified in design.md.
- [ ] Migrations never copy secret material into new plaintext columns or logs.

### Dependencies & build

- [ ] New dependency: justified against the AGENTS.md stack slate in design.md; check
      maintenance status and provenance before adding.
- [ ] `uv.lock` / `package-lock.json` updated and committed together with the change.
- [ ] Dockerfile: non-root user, minimal base image, no secrets in layers or build args.

## Release checklist (before every tag)

- [ ] `just audit` clean, or findings triaged with reasons in the PR.
- [ ] Security review pass over the full diff since the last tag.
- [ ] Live contract tests against the home Seerr instance pass; tested Seerr version recorded.
- [ ] `.env.example` contains placeholders only — no real values, no real hostnames.

## Working notes

- Spike/debug scripts that touch real tokens live outside the repo (scratch space); findings
  recorded in docs are **redacted** — names, shapes, status codes; never values.
- When the repo goes public: enable GitHub secret scanning + Dependabot alerts on day one,
  and add the root `SECURITY.md` reporting policy.

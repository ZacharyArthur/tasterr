# Security Engineering Guide

**Living document** — unlike PRD/SPEC, this is maintained as the code evolves.
[AGENTS.md](../AGENTS.md) points here; every OpenSpec change's `design.md` must answer the
relevant checklists below (enforced via `openspec/config.yaml` rules).

> Scope: how we write secure code day-to-day. The public vulnerability-reporting
> and supported-version policy is the separate root [SECURITY.md](../SECURITY.md).

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
5. Forwarded client/scheme headers are accepted only from an explicit literal-IP/CIDR
   proxy allowlist; wildcard trust is rejected.

## Checklists by area

### Any new or changed API endpoint

- [ ] Auth dependency present (session or admin) — **default-deny**; an unauthenticated
      endpoint is an explicit, justified decision in design.md.
- [ ] Mutations: CSRF origin check + rate limit applied.
- [ ] Input validated through Pydantic models — no raw dict/query passthrough.
- [ ] Explicit `response_model` — never return ORM objects or upstream JSON unfiltered.
- [ ] Errors to the client carry no stack traces, internal URLs, or upstream error bodies.
- [ ] Logs carry no tokens, cookies, credentials, or PII.
- [ ] A new state-changing route is added to the mutation-inventory regression, or
      its read-only/capability-based exemption is explicit and tested.

### Auth & session code

- [ ] Credentials are forwarded to Seerr, never stored, never logged.
- [ ] Token comparisons are constant-time (compare hashes, `secrets.compare_digest`).
- [ ] Fresh session token on every login (no fixation); logout deletes the row.
- [ ] Cookie flags: `HttpOnly`, `SameSite=Lax`, `Secure` behind HTTPS.
- [ ] Auth endpoints rate-limited tightly; failures are generic (no user enumeration).
- [ ] Forwarded IP/scheme is used only after direct proxy-peer allowlist validation;
      trusted and untrusted peer behavior is covered by regression tests.
- [ ] Authenticated/admin mutation buckets key only by server-derived user id and
      reject before upstream or database side effects.

### Outbound HTTP (`clients/`)

- [ ] Base URLs come from validated settings only — never from user input (SSRF).
- [ ] Every call has a timeout; retries are bounded.
- [ ] Browser headers are not forwarded upstream; upstream headers are not returned downstream.
- [ ] Upstream JSON is untrusted: parse into typed models, drop unknown fields.

#### Advertised Plex Media Server connections

- [ ] Select at most four Plex Media Server resources, owned-first then by advertised
      machine id; attempt at most six connections per resource in local HTTPS,
      remote-direct, relay, then stable URI order.
- [ ] Accept only `https://<host>.plex.direct:<explicit-port>` with port 1–65535,
      empty or `/` path, and no username, password, query, or fragment. Reject plain
      HTTP, missing/invalid ports, other hosts/schemes, and embedded credentials.
- [ ] Keep normal certificate-chain and hostname verification enabled. Never add
      `verify=False`, a custom trust bypass, or an arbitrary operator/server URL.
- [ ] Probe unauthenticated `/identity` with redirects disabled; accept the connection
      only when status/shape is valid and `machineIdentifier` exactly matches the
      advertised resource. Never send a token during this probe.
- [ ] After validation, send the resource token only in `X-Plex-Token`; never place it
      in a URL, redirect, log, exception, cache key/value, response, or durable row.
- [ ] Never follow redirects for plex.tv or PMS reads. A redirect is a failed
      connection/read, not a new trust decision.
- [ ] Resolve the caller's PMS-local account independently per server. Use the
      validated cloud id only when `/accounts` explicitly returns 403 for the
      self-only non-admin history path; every other account-list failure stays
      closed. Explicitly filter history and reject the whole server page if any
      row lacks or differs from that account id.

### Frontend

- [ ] No `dangerouslySetInnerHTML`; render TMDB/Seerr text as text, always.
- [ ] External URLs (Seerr redirect, Plex deep links) come from the BFF — never assembled
      client-side from data.
- [ ] No tokens or secrets in `localStorage`/`sessionStorage`; the session lives in the
      HttpOnly cookie the JS can't read.
- [ ] Browser tests use invented local fixtures, make no live request, and retain no
      trace containing placeholder credentials; failure artifacts are reviewed before publish.
- [ ] API, SPA, static, fallback, and error responses retain the fixed CSP/frame,
      MIME-sniffing, referrer, and permissions policy; HSTS appears only on trusted
      effective HTTPS.

### Database & migrations

- [ ] SQLAlchemy expressions only — no string-built SQL, ever.
- [ ] New columns holding tokens/secrets: encrypted (Fernet) and justified in design.md.
- [ ] Migrations never copy secret material into new plaintext columns or logs.
- [ ] Backup/restore instructions stop the writer or use SQLite's backup API, run an
      integrity check, preserve runtime ownership, and treat backups as sensitive.

### Dependencies & build

- [ ] New dependency: justified against the AGENTS.md stack slate in design.md; check
      maintenance status and provenance before adding.
- [ ] `uv.lock` / `package-lock.json` updated and committed together with the change.
- [ ] Dockerfile: non-root user, minimal digest-pinned base images, no secrets in
      layers or build args.
- [ ] Native container smoke proves health, SPA, non-root uid, named-volume
      persistence, isolated placeholder configuration, and unconditional cleanup.
- [ ] Every third-party workflow action is pinned to a reviewed full commit SHA;
      permissions default read-only, and package/attestation/OIDC write exists only
      on the publish job.

### Logging and release evidence

- [ ] Logs and checked-in evidence contain generic outcomes only: no live/internal
      URLs, household identities, title/viewing data, credentials, session material,
      upstream bodies, or environment dumps.
- [ ] Failure artifacts and generated reports are ignored by git and manually
      reviewed before any intentional publication.
- [ ] Release evidence identifies versions, checks, advisory dispositions, and
      generic exercised/skipped cases without reproducing sensitive command output.
- [ ] Uvicorn request access logging remains disabled, and every deployment proxy
      omits or redacts query strings before retaining or exporting access logs.

### Public repository and package release

- [ ] Root `SECURITY.md` names the supported line and GitHub private reporting path.
- [ ] GitHub private vulnerability reporting is enabled.
- [ ] Secret scanning and push protection (where available) are enabled.
- [ ] Dependabot alerts are enabled and triaged.
- [ ] Immutable releases are enabled and a `v*` tag ruleset blocks release-tag
      updates and deletion.
- [ ] `.env.example`, fixtures, history, staged files, and release notes are reviewed
      for live secrets, URLs, identities, and household data.
- [ ] Root licensing, package metadata, published image license text, and the public
      source coordinate agree.

## Release checklist (before every tag)

- [ ] `just audit` clean, or findings triaged with reasons in the PR.
- [ ] Security review pass over the full diff since the last tag.
- [ ] Live contract tests against the home Seerr instance pass; tested Seerr version recorded.
- [ ] Opt-in Plex contracts pass for every available owner/managed/shared role with
      standard TLS, machine identity, per-row history identity, account-scoped
      Continue Watching, and TMDB GUID mapping; evidence is redacted.
- [ ] `.env.example` contains placeholders only — no real values, no real hostnames.

- [ ] `just release-check` passes in the devcontainer (ordinary gate + browser +
      native container smoke).
- [ ] GHCR workflow permissions/tags are reviewed; stable manifests, image
      attestations, and a fresh registry-image deployment are verified before
      announcement.

## Working notes

- Spike/debug scripts that touch real tokens live outside the repo (scratch space); findings
  recorded in docs are **redacted** — names, shapes, status codes; never values.
- Public releases follow [RELEASING.md](RELEASING.md); policy, repository security
  features, audits, live contracts, and redacted evidence are pre-tag requirements.

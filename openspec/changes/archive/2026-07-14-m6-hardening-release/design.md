## Context

M0-M5 delivered the full v1.0 product surface. The remaining M6 work is
cross-cutting release engineering rather than another feature slice:

- the tight login bucket and M5 admin bucket exist, while `/auth/logout`,
  `/request`, `/signals`, and `/recommendations/reset` have CSRF protection but no
  loose mutation bucket;
- Uvicorn honors proxy headers but does not receive an explicit trusted-proxy
  allowlist, so the effective client IP and HTTPS scheme are deployment-dependent;
- `just check` and the PR gate cover unit/contract/build behavior, but the compiled
  SPA has not driven a real backend and the image/Compose contracts are manual;
- the Dockerfile is already multi-stage, non-root, and multi-architecture-capable,
  but there is no GHCR workflow, public quick start, operator configuration guide,
  architecture guide, vulnerability-reporting policy, or repeatable release record;
- there is no earlier tag, so the v1.0 security review covers the entire current
  tree rather than a small diff from a previous release.

The design must preserve the one-process architecture and three hard boundaries:
client-visible configuration stays an allowlist, production outbound HTTP remains
inside `clients/`, and Seerr failure never blocks browsing. Release/test machinery
must run in the required devcontainer and add no host toolchain.

## Goals / Non-Goals

**Goals:**

- Close every known M6 security, proxy, browser-smoke, container-smoke,
  documentation, and image-publishing obligation.
- Keep rate limiting local, bounded, predictable, and easy to test in the deliberate
  single-process deployment.
- Make trust of forwarding headers explicit and safe by default for direct LAN
  deployments while supporting a narrowly configured reverse proxy/tunnel.
- Exercise a compiled frontend against the real FastAPI app and real production
  clients using deterministic local upstream doubles.
- Make the same native image smoke executable locally, on PRs, and immediately
  before a GHCR publish.
- Leave a concise, redacted v1.0 release record and an operator procedure that can be
  repeated for later releases.

**Non-Goals:**

- Distributed/multi-process rate limiting, Redis, a WAF, telemetry, or a second
  runtime service.
- Product behavior after v1.0, a bundled Seerr, automatic backup scheduling, or
  database encryption.
- Replacing the existing unit/contract test pyramid with a large browser suite.
- Making live Seerr tests safe to run unattended or inventing live credentials.
- Creating a GitHub repository, choosing package visibility, administering branch
  protection, or performing commit/push/PR/merge/tag actions without the required
  operator confirmations.

## Decisions

### 1. Complete the existing token-bucket design instead of adding middleware or a dependency

`TokenBucket` remains the only limiter primitive. The app owns three bounded buckets:

- the existing **login** bucket (10 operations, refilling 10/minute), keyed by the
  effective client address because the caller is not authenticated yet;
- the existing **admin mutation** bucket (30 operations, refilling 30/minute),
  changed to key by authenticated admin user id;
- one new **authenticated mutation** bucket (60 operations, refilling 60/minute),
  keyed by authenticated user id and shared by logout, Seerr request, signal
  write/retraction, and taste reset.

A small shared FastAPI dependency spends from the authenticated bucket only after
`require_session` succeeds. Admin mutations retain their separate, stricter bucket;
they do not spend twice. All buckets retain the existing 1,024-key cap, pruning, and
fail-closed behavior for unseen keys during a key flood. A rejected request returns a
generic `429`; it performs no database or upstream mutation.

The inventory is explicit:

| Route | Classification | Limit |
|---|---|---|
| `POST /auth/plex/pin`, `POST /auth/local` | unauthenticated login mutation | tight login bucket |
| `GET /auth/plex/pin/{handle}` | high-frequency read/claim of an opaque single-use handle | explicit exemption |
| `POST /auth/logout` | authenticated mutation | shared loose bucket |
| `PUT /settings`, `POST /connection-test` | admin mutation | existing admin bucket |
| `POST /request`, `POST /signals`, `POST /recommendations/reset` | authenticated mutation | shared loose bucket |
| `POST /availability` | read-only batch whose body avoids an oversized query string | explicit exemption |

The PIN poll remains exempt because it fires about every two seconds by design, the
handle is unguessable and single-use, and rate limiting it would turn normal Plex
login into self-denial. Its existing bounded `PinStore` and generic missing/consumed
response remain the abuse controls. Availability remains exempt because it changes
no state. Both exceptions are pinned in tests and code comments.

Alternatives rejected: a global IP bucket would let one household member starve all
others behind a proxy; per-route buckets multiply state and tuning with little value;
SlowAPI or another dependency is unnecessary for one asyncio process; middleware
cannot cleanly distinguish authenticated user identity or the two read-only POST
exceptions.

### 2. Treat proxy addresses as deployment configuration, never forwarded client input

Add env-only `TASTERR_FORWARDED_ALLOW_IPS`, parsed as a comma-separated list of
literal IP addresses or CIDR networks. It defaults to loopback only and rejects the
wildcard `*`, hostnames, URLs, credentials, and malformed entries. The production
entrypoint passes the normalized list to Uvicorn's `forwarded_allow_ips` while
retaining `proxy_headers=True`.

Uvicorn therefore rewrites `request.client` and `request.url.scheme` only when the
direct peer is trusted. Direct LAN clients continue to use their socket address and
scheme. A configured cloudflared/reverse-proxy address or narrow container subnet can
supply `X-Forwarded-For` and `X-Forwarded-Proto`, allowing per-client login limits and
`Secure` cookies. An untrusted peer cannot spoof either. The allowlist is never
included in `PublicConfig`; `.env.example` and `docs/CONFIGURATION.md` explain that it
contains **proxy peer** addresses, not browser addresses, and warn against broad
networks.

Alternatives rejected: trusting `*` is unsafe if the application port is reachable
directly; ignoring forwarding leaves all tunneled users in one login bucket and can
drop `Secure` on cookies; a hard-coded Docker subnet is not portable; trusting
Cloudflare client headers in application code duplicates proven Uvicorn behavior.

### 3. Use one deterministic Playwright journey against a real app process

Add `@playwright/test` as a frontend development dependency and install Chromium only
in environments that run E2E. A test-only Python supervisor starts:

1. a deterministic local FastAPI double for the small TMDB/Seerr surface needed by
   the journey; and
2. the normal `create_app` under Uvicorn, using a temporary SQLite database and the
   compiled `frontend/dist`.

The supervisor redirects the TMDB client module's test-process base constant to the
local double and supplies the normal env-only Seerr URL. It does not add a production
test mode or a user-configurable TMDB base URL. The browser then performs one stable
local-login → personalized shell/home → detail-open → request journey and asserts the
visible success/degradation states. Fixture payloads are minimal typed upstream
shapes with invented ids/names and placeholder credentials. The suite uses role/text
locators rather than layout or animation timing and retains trace/screenshots only on
failure as CI artifacts.

`just e2e` builds the SPA and runs this journey. `just release-check` composes
`just check`, `just e2e`, and `just container-smoke`; live Seerr tests and dependency
audits stay explicit because they require operator credentials/network access and
human triage. The PR workflow runs `just check`, `just e2e`, and the container smoke
as separate blocking jobs, so the ordinary gate command remains identical locally
and in CI.

Alternatives rejected: browser-intercepting `/api` would not exercise FastAPI or the
generated client contract; hitting real TMDB/Seerr would be slow, secret-bearing, and
non-deterministic; broad E2E coverage would duplicate faster Vitest/pytest tests.

**Dependency justification:** `@playwright/test` is the single new dependency. It is
dev-only, actively maintained, already named by the founding test pyramid, and is the
smallest standard tool that drives a real browser with first-class process lifecycle,
tracing, and accessible locators. No Python or runtime dependency is added, and
`package-lock.json` is committed with it.

### 4. Make one native container smoke own image and Compose contracts

A Linux shell script behind `just container-smoke` builds the production Dockerfile
and uses an isolated Compose project-managed network plus temporary placeholder env.
It asserts:

- the container becomes healthy and `/api/v1/health` returns `200`;
- `/` serves the compiled SPA;
- the runtime uid is non-zero;
- `/data/tasterr.db` exists; a smoke marker written with Python's stdlib `sqlite3`
  survives a forced container recreation against the same named volume; and
- cleanup removes the isolated containers, network, image tag, and test volume even
  after failure.

The test never copies `.env`, never uses a real integration coordinate, and never
prints environment contents. The base Compose file uses its ordinary managed network
and reaches Seerr exclusively through `SEERR_INTERNAL_URL`, so a routable LAN URL
requires no pre-created network or Seerr-stack change. The commented same-project
Seerr service remains optional documentation. A small
`docker-compose.seerr-network.yml` override joins an operator-named external network
only when Seerr runs on the same Docker host in another Compose project and service-
name discovery is desired. Contract tests render both paths.

Alternatives rejected: inspecting only the Dockerfile cannot prove runtime uid,
health, or persistence; making every deployment join an external network adds a
meaningless prerequisite for remote/LAN Seerr and Docker networks cannot span hosts;
mounting a host directory would not verify the named-volume contract.

### 5. Keep two workflows and publish only after native verification

The existing `gate.yml` remains the PR workflow and gains separate E2E and container
smoke jobs. A new `image.yml` is the only publish workflow. It runs on pushes to
`main` and stable `v*` tags, executes the native container smoke first, then uses
Buildx/QEMU to publish `linux/amd64` and `linux/arm64` to
`ghcr.io/${{ github.repository }}`.

Image tags are deterministic:

- every publish gets immutable `sha-<commit>` metadata;
- `main` updates the moving `main` tag;
- a SemVer tag such as the first stable `v1.0.0` produces `1.0.0`, `1.0`, and `1`,
  and stable releases update `latest`.

The first stable Git tag is `v1.0.0`; the founding documents' “v1.0 tag” names the
release line, while the actual tag follows SemVer. Backend package metadata and the
private frontend manifest move to `1.0.0` in the release change. OCI labels come from
Git metadata. The workflow receives `contents: read` and `packages: write` only,
never runs a push step for pull requests, and passes no secrets as Docker build args.
Third-party actions in both workflows are pinned to immutable commit SHAs with their
human-readable release versions in comments.

Alternatives rejected: Docker Hub adds another credential and registry; building only
amd64 violates the deployment goal; building locally and manually pushing is not
repeatable; publishing from a PR exposes package credentials to untrusted code.

### 6. Separate durable operator docs from frozen founding rationale

Do not edit `docs/PRD.md` or `docs/SPEC.md`. Add and cross-link:

- root `README.md`: product summary, supported v1.0 scope, quick Compose start, and
  links to the living operator/architecture/security docs;
- `docs/CONFIGURATION.md`: every env variable, secret generation, first boot,
  existing-Seerr networking, HTTPS/proxy allowlist, named-volume backup/restore,
  upgrade/rollback, and troubleshooting/degraded modes;
- `docs/ARCHITECTURE.md`: process/module boundaries, request flows, storage/cache,
  identity/secrets, generated types, and Seerr degradation;
- root `SECURITY.md`: private vulnerability-reporting route and supported-version
  policy, distinct from the developer threat model at `docs/SECURITY.md`;
- `docs/RELEASING.md`: ordered pre-tag audits, live contracts, security review,
  release check, archive/merge/tag/publish/verify/rollback procedure; and
- `docs/releases/v1.0.0.md`: redacted release evidence (date, checks, audit
  disposition, live Seerr version/cases, known limitations), written before tagging.

`docs/DEFERRED.md` loses only entries actually closed. Data-dependent live cases may
be recorded as skipped only when their documented preconditions are absent; the
stored-token Plex contract is mandatory for v1.0 because it protects the silent
re-auth path. Evidence contains outcomes and versions, never credentials, real
hostnames, household names, request titles, tokens, or cookies.

### 7. The release tag is an operator step after the atomic code/spec merge

Implementation finishes the code, docs, specs, release record, and all locally
available checks on `change/m6-hardening-release`; the change is then archived on
that branch before the PR, as required. The squash merge creates the releasable main
commit. Only after the release checklist is complete on that commit does the operator
create and push `v1.0.0`, verify the GHCR manifest contains both architectures, run a
fresh-install smoke from the registry image, and publish release notes.

Rollback is tag/digest based: keep the SQLite volume, stop the failed image, restore
the pre-upgrade database backup when a migration is not backward-compatible, and run
the preceding known-good digest. M6 adds no migration, so v1.0 rollback is an image
rollback with the same database file. No task silently commits, pushes, opens a PR,
or tags; each remains subject to explicit confirmation.

## Security considerations

### Changed API endpoints

- No new browser endpoint is added. Every changed mutation already has the shared
  session/admin dependency, Pydantic input (or no body), explicit secret-free
  response model, generic errors, and same-origin check. The change adds the missing
  rate limit before database/upstream mutation and tests `429` with no side effect.
- `/availability` is demonstrably read-only and PIN polling uses an opaque single-use
  capability; their explicit exemptions are tested rather than inferred from HTTP
  method alone.
- Rate-limit logs, if any, contain only route/outcome and stable internal user id;
  they contain no title id, viewing behavior, credentials, token, cookie, upstream
  body, or internal URL.

### Auth and sessions

- Credential forwarding, fresh session minting, hashed session storage, encrypted
  Plex tokens, logout revocation, and generic failures are unchanged.
- Forwarded scheme/client values are accepted only from validated trusted peers,
  keeping `Secure` correct behind HTTPS without letting a direct client spoof its IP
  or downgrade/upgrade cookie handling.
- Login remains tightly IP-limited; authenticated/admin limits key by server-derived
  user id. No client-supplied identifier chooses a bucket.

### Outbound HTTP

- Production outbound behavior is unchanged and remains solely in `clients/`, with
  validated settings, timeouts, bounded TMDB retry, typed upstream parsing, and no
  browser/upstream header passthrough.
- The E2E upstream double accepts calls on loopback in test support; it does not add a
  production outbound path or configurable SSRF target. Fixture bodies are treated
  through the same typed production clients.

### Frontend

- The E2E adds no application rendering primitive, external URL construction, or
  browser storage. It uses placeholder login data only; CI receives no live secret.
- Existing `dangerouslySetInnerHTML`, external-link, storage, generated-type, and
  `PublicConfig` regression checks are included in the full-tree security review.

### Database

- No schema or secret column changes. All application access remains SQLAlchemy-only.
  The container smoke uses stdlib `sqlite3` only against its disposable isolated
  volume to prove persistence and cleans it afterward.
- Backup instructions stop the writer before copying the SQLite file (or use SQLite's
  backup mechanism), validate the backup, and make restore ownership explicit.

### Dependencies and build

- `@playwright/test` is dev-only and justified above; its lockfile update is atomic.
  No runtime or Python dependency is added.
- `just audit` is run and findings are either cleared or explicitly triaged in the
  release record. The full tree is reviewed because no previous tag exists.
- Docker remains minimal, non-root, and secret-free. CI uses least privilege,
  immutable action pins, no secrets on PR code, and no credentials/build args in
  image layers. `.env.example` remains placeholder-only and its regression test is
  extended for the proxy setting.

### Public release

- Root `SECURITY.md` directs reports to a private channel; the operator checklist
  includes enabling GitHub private vulnerability reporting, secret scanning, and
  Dependabot alerts when the repository becomes public.
- Release evidence is redacted as described above. GitHub/package visibility is an
  operator choice and does not weaken any application default.

## Risks / Trade-offs

- **[One-process buckets reset on restart and do not coordinate replicas]** → This is
  consistent with the explicit one-process architecture; docs state the limitation
  and multi-replica deployment remains unsupported.
- **[A proxy subnet configured too broadly permits spoofed forwarding headers]** →
  Reject wildcard trust, default to loopback, validate IP/CIDR syntax, and document
  narrow peer addresses with negative tests for untrusted peers.
- **[A shared per-user loose bucket can briefly throttle legitimate rapid signals]**
  → Capacity 60 with continuous refill tolerates normal browsing, returns a
  recoverable generic 429, and can be adjusted as a code-owned constant if real use
  proves otherwise.
- **[The E2E fixture can drift from upstream contracts]** → It covers UI/backend
  integration only; typed client unit fixtures and the mandatory live Seerr suite
  remain the authority for upstream contracts.
- **[Browser and multi-arch CI increase time]** → Keep one Chromium journey, cache npm
  and Playwright assets, run native smoke before the one multi-arch publish, and avoid
  duplicating unit scenarios.
- **[Main publish can succeed while one emulated architecture only builds, not runs]**
  → Native smoke proves runtime behavior and Buildx proves both architectures build;
  the release checklist inspects the manifest and calls for an operator smoke on the
  household architecture.
- **[No remote/live credentials exist while implementation is underway]** → All code
  and deterministic checks remain implementable locally; the release record and tag
  cannot be called complete until the operator supplies the documented external
  prerequisites.

## Migration Plan

1. Add proxy settings and rate-limit behavior with focused backend tests; default
   loopback trust preserves direct deployments and requires no database migration.
2. Add E2E and container-smoke commands, run them in the devcontainer, then add their
   blocking PR jobs.
3. Add the image workflow, action hardening, version metadata, and operator/public
   docs; remove only fulfilled deferrals.
4. Run the full security review, `just check`, E2E, container smoke, audits, and live
   Seerr suite; fill the redacted v1.0.0 record.
5. Archive the OpenSpec change on the branch, merge by the normal squash workflow,
   rerun release checks on main, create `v1.0.0`, and verify GHCR and a fresh deploy.
6. On failure before tagging, fix on the change branch. On failure after publish,
   remove/move no immutable tag; deploy the prior digest (if any), restore the
   validated backup when necessary, fix forward, and issue the next patch version.

## Open Questions

No code-design question blocks implementation. Before the actual tag, the operator
must supply three deployment facts that cannot be inferred from this repository: the
GitHub remote/package visibility, the exact trusted proxy address/CIDR for the target
stack, and the live Seerr/Plex test credentials. They are recorded release inputs,
not defaults to guess or commit.

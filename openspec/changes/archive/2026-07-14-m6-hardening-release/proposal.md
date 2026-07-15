## Why

Tasterr's v1.0 product surface is complete, but the repository is not yet safe or
repeatable to release: several authenticated mutations lack the planned loose rate
limit, proxy trust is implicit, the real browser and container paths are not covered
end to end, and no operator or image-publishing path exists. This change completes
**PRD/SPEC milestone M6 (Hardening & release)** so the first tag is supported by an
auditable security pass, reproducible checks, and an amd64/arm64 image rather than a
one-off manual build.

## What Changes

- Apply bounded in-process rate limits to every state-changing endpoint, retaining
  the tighter login bucket and explicitly exempting read-only POSTs such as batch
  availability hydration.
- Make forwarded-header handling default-deny: only configured proxy addresses may
  supply the client IP and HTTPS scheme used by rate limiting and Secure cookies.
- Add a light Playwright smoke against a real Tasterr backend with deterministic
  local TMDB/Seerr doubles, covering login, home browsing, detail, and request.
- Add automated image/Compose smoke coverage for health, SPA serving, non-root
  execution, SQLite volume persistence, and URL-only deployment without a required
  external Docker network.
- Publish the multi-stage image to GHCR for amd64 and arm64 through GitHub Actions,
  with immutable commit/version tags and release tags suitable for v1.0.
- Add the missing release-facing documentation: repository quick start,
  `docs/CONFIGURATION.md`, `docs/ARCHITECTURE.md`, a vulnerability-reporting policy,
  and an explicit backup/restore, upgrade, proxy, audit, live-contract, and tagging
  checklist.
- Perform and record the v1.0 security review, dependency-audit disposition, live
  Seerr contract result/version, and container/browser release evidence before the
  tag is created.
- Remove the M6 entries that this change closes from the deferred-work ledger and
  soften the compose living-spec wording to match the intentionally commented Seerr
  example.

## Capabilities

### New Capabilities

- `release-readiness`: Defines the operator documentation, security evidence,
  repeatable pre-tag verification, vulnerability reporting, and v1.0 release record.

### Modified Capabilities

- `app-settings`: Adds an env-only trusted-proxy allowlist and documents it in the
  complete placeholder-only deployment configuration.
- `user-auth`: Trusts forwarding headers only from the configured proxy allowlist and
  applies the planned loose mutation limit to logout while preserving tight login
  limits.
- `media-requests`: Adds the shared authenticated-mutation rate limit to title
  requests without changing Seerr degradation behavior.
- `taste-signals`: Adds the shared authenticated-mutation rate limit to interaction
  writes and retractions.
- `taste-recommendations`: Adds the shared authenticated-mutation rate limit to taste
  reset.
- `container-deploy`: Verifies image and Compose behavior automatically and publishes
  a tagged multi-architecture GHCR image; makes routable Seerr URLs the zero-network-
  configuration default while retaining an optional same-host external-network
  override.
- `dev-tooling`: Adds the deterministic Playwright and release-verification commands
  and their CI coverage while keeping `just check` as the ordinary identical PR gate.

## Impact

- **Backend:** shared rate-limit dependencies and app state, production Uvicorn proxy
  configuration, settings validation, and focused endpoint tests. No database schema
  change and no new runtime process or service.
- **Frontend/test tooling:** one Playwright development dependency, a small smoke
  suite, and deterministic local upstream fixtures; no production frontend behavior
  or dependency changes.
- **Deployment/CI:** Docker/Compose smoke scripts, one image workflow alongside the
  existing gate workflow, GHCR package permissions/tags, and documented operator
  configuration. The workflow is repository-portable and does not assume a current
  remote name.
- **Documentation/security:** new public/operator docs, a root reporting policy,
  updates to `docs/SECURITY.md` and `docs/DEFERRED.md`, and checked-in release
  evidence containing no secrets, credentials, household identifiers, or live URLs.

## Non-goals

- No v1.x/v2 product work: Plex playback links, onboarding, Plex history,
  continue-watching, household blending, native apps, or telemetry.
- No Redis, distributed rate limiter, WAF, new runtime dependency, or multi-process
  deployment support; the deliberate single-process architecture remains.
- No automatic backup scheduler, database encryption, or defense against an attacker
  with host/file access. The release documents safe operator backup and restore.
- No bundled Seerr instance; the compose example continues to target an existing
  household Seerr and keeps the optional service commented out.
- No automatic destructive live request test, package-visibility change, repository
  creation, branch-protection administration, push, PR, merge, or tag. Those external
  release actions remain explicit operator steps under the repository's confirmation
  rules.

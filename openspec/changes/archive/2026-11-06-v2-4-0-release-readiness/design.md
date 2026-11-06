## Context

See proposal.md. Main at cab7218 contains untagged linked accounts and eight
subsequent archived features after v2.3.1. The archived v2.3.0 readiness change
and v2.3.1 preparation commit bde1f59 provide the release structure.

## Goals / Non-Goals

Prepare consistent, reviewable v2.4.0 metadata and evidence without changing
runtime behavior or adding dependencies. Preserve historical release scenarios
and evidence. Stop before external git writes and publication.

## Decisions

- Use 2.4.0 for additive operator functionality and opt-in/opt-out changes.
  Define supported contracts in CONTRIBUTING.md: configuration/environment,
  images/tags, health, persisted data and upgrade/downgrade paths, and documented
  operator procedures. The private /api/v1 backend ships with its only client;
  its reset 204 response is documented but does not require a major release.
- Reuse existing manifests, docs and regressions; change only the local package
  entry in uv.lock and root package entries in package-lock.json. No dependency
  refresh or runtime compatibility wrapper is necessary.
- Promote unreleased.md to v2.4.0.md and update its callers. Do not retain an
  empty file: tests and release instructions can reference the current record;
  future feature work creates the next unreleased notes.
- Require Seerr, owner/managed/shared Plex, Jellyfin and Trakt live contracts.
  Use the owner's fresh 2026-11-05 automated pass on the code now at cab7218;
  release-only metadata and documentation do not change integration paths.
  Record only confirmed versions, generic outcomes and documented absent-data skips.
- Run release-check and audit fresh, validate/archive atomically and run check
  afterward. Protected-main CI and candidate/tag-time checks remain later steps.
- Keep existing Details headings while extracting long documentation, evidence,
  verification and publication behaviors into focused added requirements.

## Security considerations

Review the full v2.3.1..HEAD release scope against docs/SECURITY.md, including
previously merged behavior, not only this metadata diff.

- Endpoints: confirm session/admin dependencies, same-origin and mutation buckets,
  typed bounded inputs and public response models, generic errors and the
  mutation-inventory regression. This change adds no endpoint or permission.
- Auth/sessions: confirm hashed sessions, encrypted linked Plex/Seerr/Trakt
  credentials, session-bound link handles, admission/admin checks, Jellyfin token
  logout, default-refused empty passwords, 30-day sliding/90-day absolute expiry,
  secure cookie/proxy handling and caller-scoped unlink/delete cancellation.
- Outbound HTTP: confirm only clients perform HTTP, validated/fixed hosts, verified
  TLS, refused redirects, bounded reads/timeouts and typed upstream parsing.
  Review Plex identity/history isolation, Jellyfin user scoping, Seerr capability
  refusal and Trakt refresh persistence during cancellation.
- Frontend: retain text rendering, initials avatars, HttpOnly sessions, no token
  storage, public projections, security headers and invented browser fixtures.
- Database: retain foreign-key-safe transactional migrations, encrypted secrets,
  stopped-writer validated backups, cascades and cancellation before destructive
  changes. Document every downgrade loss from 0010 through 0007; this preparation
  adds no migration and performs no production migration.
- Dependencies/build: audit both locks, retain digest-pinned non-root builds and
  fully pinned Actions with minimal permissions. Verify health, SPA, private logs,
  hardened headers, volume persistence and cleanup in native smoke.
- Logs/evidence: review tracked examples, fixtures, release history and final diff
  for private material. Access logs remain disabled; independently record proxy
  query-string logging verification or its operator-verification limitation.
- Publication: read back private reporting, scanning/push protection, dependency
  maintenance, immutable releases, main/version-tag rules and workflow defaults.
  Do not infer remote settings from source or retain raw private upstream output.

## Risks / Trade-offs

- Incomplete live version/cleanup evidence or unavailable repository access blocks
  final disposition; do not invent results or rerun live suites without approval.
- Deployment proxy logging is operator-owned; record what was actually verified.
- Post-tag failure preserves the immutable tag and fixes forward in a patch.

## Migration Plan

No new migration in this preparation. Upgrade from v2.3.1 automatically applies
0007–0010 and signs members out once. Preserve the secret key, Compose project and
volume; validate backups and verify health/sign-in after upgrade. Immediate rollback
uses the known-good v2.3.1 digest with its matching backup or the current image's
explicit 0010 → 0009 → 0008 → 0007 → 0006 downgrade. Never start v2.3.1 on 0010.

## Context

See proposal.md. PR #40 is merged after v2.2.0. Seerr settings reads and TV
request bodies changed; Plex integration paths did not. Existing release gates apply.

## Goals / Non-Goals

Prepare an accurately evidenced v2.3.0. Do not alter the season-selector behavior,
release gates, frozen blueprints or historical evidence.

## Decisions

- Update existing manifests, lock metadata, current docs and regressions together.
  Keep dependency versions unchanged unless a fresh audit requires a targeted fix.
  No new dependency is needed.
- Extend release-readiness requirements to v2.3.0, preserving prior evidence/live
  scenarios. The immediate image rollback target is v2.2.0.
- Run fresh deterministic checks, audits and live Seerr contracts. Prefer fresh
  owner/managed/shared Plex contracts; any unchanged-Plex exception requires explicit
  owner disposition with a dated complete baseline and fresh integrated manual evidence.
- Record unresolved requirements as pending. Do not carry forward prior owner
  exceptions as approval for this release.
- Review the exact commit/PR text before publication. Archive only after all branch
  tasks pass, then use protected-main CI, candidate verification and immutable tags.

- Correct the existing Plex live test's exhausted candidate budget: irrelevant or
  already-mapped episode rows must not consume still-needed movie probes. Keep
  the same maximum candidate metadata attempts and both mandatory assertions.

## Security considerations

Review the full v2.2.0..HEAD scope against docs/SECURITY.md. Season requests retain
session, CSRF and rate guards, typed bounded unique season numbers, fresh member and
variant permissions, fail-closed partial/Specials policy and member-cookie attribution.
Only typed public capability flags reach the browser; settings/API keys stay in clients.
Timeouts and existing outbound boundaries remain. Rejected/no-op requests produce no
success or taste signal. Frontend text rendering, nested focus/keyboard isolation and
HttpOnly sessions remain; there is no new credential storage or migration.
Review source, lock provenance, non-root image, workflow pins and minimum permissions.
CodeQL scanning adds security-events write only to its analysis job.
Verify public repository controls and staged evidence separately; never retain credentials,
private coordinates or household data. Check deployment query-string log redaction
or obtain a release-specific disposition. Artifact attestations and immutable GitHub
Releases are enabled controls to verify before publication, not inferred from source.

## Risks / Trade-offs

- Missing live credentials -> keep mandatory checks pending; no changed-Seerr waiver.
- Missing optional library data -> document only valid absent-data skips.
- Post-tag failure -> preserve the immutable tag and fix forward with a patch.

## Migration Plan

No new migration. Validate a SQLite backup before upgrading the existing volume.
Image-only rollback uses the known-good v2.2.0 digest on the same schema.
Rollback across migration 0006 to v1.1 retains the documented downgrade/backup procedure.

## Why

The Plex connection-fallback fix is merged on `main`, but package metadata and
current release material still identify `2.1.0`. The repository needs its
audited release-readiness step before the patch can be tagged and published as
`v2.1.1`.

## What Changes

- Set backend, frontend, lockfile, and release-regression metadata to `2.1.1`.
- Apply compatible security patches to the existing Vitest and `js-yaml`
  development dependency chain so the locked frontend audit is clean.
- Advance the copyable README deployment example and current release guidance to
  `v2.1.1` without rewriting historical release evidence or migration facts.
- Update the release-readiness specification for the v2.1.1 patch sequence.
- Scope the retained-live-baseline exception to integrations whose request/response
  path is unchanged while continuing to require fresh automation for changed
  integrations.
- Add a redacted `v2.1.1` pre-tag evidence record covering the Plex fallback fix,
  deterministic checks, dependency audits, security review, live contracts,
  known limitations, and rollback basis.
- After gated merge, verify the multi-architecture SHA candidate, public
  anonymous install, and attestation before creating `v2.1.1`; then verify
  stable aliases and publish an immutable GitHub Release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: Advance package, documentation, evidence, and publication
  requirements from v2.1.0 to the audited v2.1.1 patch release.

## Non-goals

- Changing runtime behavior, API contracts, runtime dependencies, database
  schema, or workflows during release preparation.
- Weakening deterministic checks, dependency audits, changed-integration live
  contracts, repository security controls, provenance verification, or clean-install
  smoke.
- Recording private URLs, credentials, household identities, title/viewing data,
  raw logs, or unredacted live evidence.
- Rewriting historical release evidence, migration boundaries, or published tags.
- Moving, deleting, or reusing a published tag if post-tag verification fails.

## Impact

- Metadata: backend/frontend manifests, both lockfiles, version regressions, and
  compatible audit-driven development dependency patches.
- Documentation: README, releasing guide, living release-readiness spec, and
  `docs/releases/v2.1.1.md` evidence.
- Delivery: protected PR gates, GHCR candidate/stable tags and attestations, the
  immutable `v2.1.1` Git tag, and GitHub Release.
- Milestone: advances the existing release-readiness capability for the merged
  Plex connection-discovery reliability fix.

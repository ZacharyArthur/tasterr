## Why

The tooling, Plex recovery, and discovery-rail improvements are merged on `main`,
but package metadata and current release material still identify `2.0.0`. The
repository needs its audited release-readiness step before `v2.1.0` can be tagged
and announced.

## What Changes

- Set backend, frontend, lockfile, and release-regression metadata to `2.1.0`.
- Advance the copyable README deployment example and supported-version policy to
  the v2.1 stable line without rewriting historical v2.0 migration facts.
- Update current release/configuration guidance for the v2.1 candidate, stable
  aliases, attestation, clean-install, upgrade, and rollback sequence.
- Add a redacted `v2.1.0` pre-tag evidence record covering the merged scope since
  v2.0.0, deterministic checks, dependency audits, security review, live-contract
  disposition, known limitations, and rollback basis.
- After gated merge, verify the multi-architecture SHA candidate, public anonymous
  install, and attestation before creating `v2.1.0`; then verify stable aliases and
  publish an immutable GitHub Release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: Advance package, documentation, evidence, and publication
  requirements from the v2.0 stable line to the audited v2.1 release.

## Non-goals

- Changing runtime behavior, API contracts, dependencies, or database schema.
- Weakening deterministic checks, dependency audits, live contracts, repository
  security controls, provenance verification, or clean-install smoke.
- Recording private URLs, credentials, household identities, title/viewing data,
  raw logs, or unredacted live evidence.
- Rewriting the historical v2.0 evidence, migration boundary, or published tags.
- Moving, deleting, or reusing a published tag if post-tag verification fails.

## Impact

- Metadata: backend/frontend manifests, both lockfiles, and version regressions.
- Documentation: README, public support policy, configuration/releasing guides,
  living release-readiness spec, and `docs/releases/v2.1.0.md` evidence.
- Delivery: protected PR gates, GHCR candidate/stable tags and attestations, the
  immutable `v2.1.0` Git tag, and GitHub Release.
- Milestone: advances the existing release-readiness capability for the merged
  post-v2.0 tooling, Plex recovery, and richer discovery-rail changes.

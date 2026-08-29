## Why

The completed Plex-aware personalization milestone is merged on `main`, but the
published stable line and operator-facing release material still identify v1.1. The
repository now needs the separate audited release step reserved by that feature
change before `v2.0.0` can be tagged and announced.

## What Changes

- Set backend, frontend, lockfile, and release-regression metadata to `2.0.0`.
- Pin the copyable README deployment example and supported-version policy to the
  v2.0 stable line.
- Update the release and configuration guides for the v2 migration, downgrade,
  candidate, stable-image, attestation, and clean-install sequence.
- Add a redacted `v2.0.0` pre-tag evidence record covering deterministic checks,
  dependency audits, security review, live Seerr/Plex contracts, known limitations,
  and rollback basis.
- After gated merge, verify the multi-architecture SHA candidate, public anonymous
  install, and attestation before creating `v2.0.0`; then verify stable aliases and
  publish an immutable GitHub Release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: Advance package/docs/evidence requirements from the v1 line
  to the separately audited v2.0 release, including the Plex live-contract gate and
  migration-aware rollback.

## Non-goals

- Changing runtime product behavior, API contracts, dependencies, or database
  schema beyond the already-merged Plex-aware implementation.
- Weakening or waiving deterministic checks, dependency audits, live contracts,
  repository security controls, provenance verification, or clean-install smoke.
- Recording private URLs, credentials, household identities, title/viewing data,
  raw logs, or unredacted live evidence.
- Moving, deleting, or reusing a published tag if any post-tag verification fails.

## Impact

- Metadata: backend/frontend manifests, both lockfiles, and version regression tests.
- Documentation: README, public support policy, configuration/releasing guides, and
  a new `docs/releases/v2.0.0.md` evidence record.
- Delivery: protected PR gates, GHCR candidate/stable tags and attestations, the
  immutable `v2.0.0` Git tag, and GitHub Release.
- Milestone: publishes the founding PRD's v2 Plex-aware personalization scope as the
  current supported stable line.

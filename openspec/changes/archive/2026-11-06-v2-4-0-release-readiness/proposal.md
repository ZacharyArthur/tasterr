## Why

The linked-account work and eight subsequent archived feature changes have not
shipped in a tagged release. Advance the existing release-readiness capability to
prepare v2.4.0 with accurate upgrade guidance and fresh release evidence.

## What Changes

- Synchronize package/lock metadata, image pins, support policy, current docs and
  release regressions at 2.4.0.
- Promote the unreleased notes to v2.4.0 evidence, including migrations
  `0007`–`0010`, default-on watched hiding and operator-managed Trakt setup.
- Define supported SemVer contracts and the private bundled-SPA API boundary.
- Require Trakt alongside Seerr, Plex and Jellyfin in the live release gate.
- Record fresh deterministic checks, audits, repository/security review and the
  owner's 2026-11-05 automated live results without private data.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: current version, supported line, mandatory live suites,
  evidence, versioned operator contracts and immediate rollback target.

## Impact

Package metadata, release/operator docs, existing documentation regressions and
release specifications. No new endpoint, dependency, migration or runtime behavior.

## Non-goals

Do not rerun live suites, change product behavior, tag, publish, close issues or
relax release gates. Commit, push and PR creation require separate approval.

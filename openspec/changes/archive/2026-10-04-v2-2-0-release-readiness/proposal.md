## Why

Publish the merged request-destination and household discovery-exclusion features as v2.2.0, advancing the existing release-readiness capability. Current version metadata still names v2.1.1 and dependency audits identify compatible security fixes required before publication.

## What Changes

- Align package/lock metadata, current deployment docs, security support policy and release regressions on v2.2.0.
- Patch only audit-affected existing dependency chains, with fresh audits and deterministic checks.
- Record full release security review, fresh changed-integration Seerr contracts and the existing Plex verification policy in redacted release evidence.
- Archive and merge readiness before verifying the main candidate, tagging and publishing the immutable release.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: Current stable coordinates, support line, v2.2.0 evidence and publication/rollback order.

## Non-goals

New product behavior, altered live-contract exception policy, new dependencies, database migrations, workflow changes, broad dependency refreshes or retroactive edits to historical release evidence.

## Impact

Backend/frontend manifests and locks, documentation/version regressions, living release specification and docs/releases/v2.2.0.md. Existing protected-main and immutable-tag/image workflows remain unchanged. Publication requires final evidence, exact-text approval and live verification.

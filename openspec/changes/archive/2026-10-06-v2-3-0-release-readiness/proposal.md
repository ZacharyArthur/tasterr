## Why

The merged TV season selector in PR #40 adds a user-visible capability after v2.2.0.
Prepare v2.3.0 through the existing release-readiness capability and publication gates.

## What Changes

- Advance package/lock metadata, current operator docs and support policy to 2.3.0.
- Correct the live Plex check to count only still-needed GUID candidates within its existing budget.
- Record fresh release verification and accurate season-selection scope and limitations.
- Update the living release requirements while retaining historical release evidence.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `release-readiness`: current version, supported line, evidence and immediate rollback target.

## Impact

Package metadata, release docs, existing regression tests and release specification.
No new dependency, endpoint, migration or product behavior.

## Non-goals

No further season-selector changes, broad dependency refresh or relaxed release gates.

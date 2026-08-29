## 1. Version and Release Documentation

- [x] 1.1 Set backend/frontend package and lock metadata to `2.0.0`, update the
  release-version regression, and prove unrelated dependency versions are unchanged.
- [x] 1.2 Update README, public support policy, configuration, releasing, and
  documentation regressions for the v2 image, migration-aware rollback, live Plex
  gate, candidate verification, stable aliases, and immutable GitHub Release.
- [x] 1.3 Add `docs/releases/v2.0.0.md` with redacted scope, upgrade/rollback,
  limitations, and placeholders only for outcomes that must be measured in this
  release change; do not predict post-merge/tag facts.

## 2. Pre-Tag Verification and Evidence

- [x] 2.1 Verify repository/package security controls, workflow permissions/action
  pinning, public support/license coordinates, placeholder-only fixtures/env, and
  absence of live/private material or generated failure artifacts.
- [x] 2.2 Run `just release-check` inside the devcontainer and record its exact generic
  outcome and test counts in the v2 evidence.
- [x] 2.3 Run both locked dependency audits, resolve actionable findings or record
  advisory-specific dispositions, and update the v2 evidence.
- [x] 2.4 Run mandatory live Seerr and owner/managed/shared Plex contracts from a
  mode-0600 temporary file where current credentials permit; otherwise record the
  release owner's explicit acceptance of complete dated automated baselines plus a
  fresh manual test without claiming a fresh automated pass.
- [x] 2.5 Review the complete `v1.1.0..HEAD` security and migration scope, finalize the
  approved-for-release evidence, and confirm the post-merge candidate/tag runbook is
  executable without a post-release source commit.
- [x] 2.6 Run strict OpenSpec validation and fix every release artifact issue.

## 3. Final Quality Gate

- [x] 3.1 Run `just check` inside the devcontainer and fix any failures.

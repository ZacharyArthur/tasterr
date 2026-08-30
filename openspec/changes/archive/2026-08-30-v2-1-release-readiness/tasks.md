## 1. Version and Release Documentation

- [x] 1.1 Set backend/frontend package and lock metadata to `2.1.0`, update the
  release-version regressions, and verify unrelated dependency versions are
  unchanged.
- [x] 1.2 Advance the README, support policy, current configuration/releasing text,
  and documentation regressions to v2.1 while preserving historical v2.0 evidence
  and migration facts; verify the focused documentation/version tests pass.
- [x] 1.3 Add `docs/releases/v2.1.0.md` with redacted scope, upgrade/rollback,
  limitations, and only branch-verifiable outcomes; verify the evidence regression
  passes without predicting post-merge/tag facts.

## 2. Pre-Tag Verification and Evidence

- [x] 2.1 Review the complete `v2.0.0..HEAD` scope and repository contents against
  `docs/SECURITY.md`; record generic results and verify no secret, private, or
  generated failure material is staged.
- [x] 2.2 Run `just release-check` and `just audit` inside the devcontainer, resolve
  actionable failures or record advisory-specific dispositions, and update the
  v2.1 evidence with exact generic outcomes.
- [x] 2.3 Run mandatory live Seerr and owner/managed/shared Plex contracts when
  current credentials permit; otherwise record only a qualifying release-owner
  baseline/manual-test exception and never claim a fresh automated pass.
- [x] 2.4 Verify GitHub repository security controls and the candidate/tag runbook,
  record the generic result, and confirm post-merge facts require no source commit.
- [x] 2.5 Run strict OpenSpec validation and fix every release artifact issue.

## 3. Final Quality Gate

- [x] 3.1 Run `just check` inside the devcontainer and fix any failures.

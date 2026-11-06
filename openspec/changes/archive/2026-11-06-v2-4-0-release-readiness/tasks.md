## 1. Release preparation

- [x] 1.1 Advance backend/frontend package and lock metadata, image pins, current operator docs and support policy to 2.4.0; clarify the private SPA API/SemVer boundary; update existing regressions and verify focused tests and just check.
- [x] 1.2 Promote unreleased notes to docs/releases/v2.4.0.md with all untagged scope, default-on watched hiding, Trakt setup, exact v2.3.1 downgrade losses and honest limitations; verify documentation regressions.
- [x] 1.3 Update release-readiness requirements for 2.4.0, mandatory Trakt live contracts and v2.3.1 rollback while preserving historical scenarios and Details headings; verify strict change validation.

## 2. Release evidence

- [x] 2.1 Run fresh devcontainer just release-check and both dependency audits; resolve blockers and record generic results.
- [x] 2.2 Record the owner's 2026-11-05 automated Seerr, owner/managed/shared Plex, Jellyfin and Trakt pass on the code at cab7218, tested versions, cleanup and valid absent-data skips; do not rerun live suites.
- [x] 2.3 Review v2.3.1..HEAD against docs/SECURITY.md, inspect open Dependabot alerts and repository controls, and review examples/fixtures/history/final diff for private data; record verified results and proxy logging disposition.
- [x] 2.4 Finalize the branch-verifiable pre-tag disposition only after mandatory evidence resolves; leave merged-candidate and tag-time facts to the GitHub Release.

## 3. Validate and archive

- [x] 3.1 Run openspec validate v2-4-0-release-readiness --strict and just release-check, then review the complete release diff before archival.

## Workflow follow-up

- Archive on this branch with openspec archive v2-4-0-release-readiness --yes; review the synchronized specification and run openspec validate --specs --strict. Completed: all 20 living specifications passed.
- Run just check once more and fix any failures. Completed: 1,610 backend and 273 frontend tests passed, together with lint, format, typing, boundaries, generated-type freshness and production build.

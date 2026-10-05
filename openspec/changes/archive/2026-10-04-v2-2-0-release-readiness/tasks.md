## 1. Version, Dependencies and Documentation

- [x] 1.1 Advance backend/frontend package and lock metadata to 2.2.0; apply only compatible audit-required anyio, urllib3, undici and brace-expansion updates; verify lock scope, installed versions, both audits and the full gate.
- [x] 1.2 Update current README/releasing/security support text and version/docs regressions, retaining historical releases and migration facts; verify focused tests and strict delta validation.
- [x] 1.3 Create redacted docs/releases/v2.2.0.md with accurate scope, rollback and limitations; keep unresolved gates pending and verify evidence regressions before finalizing disposition.

## 2. Release Verification

- [x] 2.1 Review full v2.1.1..HEAD scope against docs/SECURITY.md and verify repository security controls; record generic outcomes and inspect staged material for secrets/generated artifacts.
- [x] 2.2 Run devcontainer just release-check and separate audits; resolve failures and record exact generic results.
- [x] 2.3 Run fresh mandatory Seerr contracts, including destination persistence, and owner/managed/shared Plex contracts with secure operator-provided credentials/disposable IDs; verify cleanup and record only upstream versions and generic outcomes. Any unchanged-Plex exception requires explicit owner disposition under the existing policy.
- [x] 2.4 Finalize evidence only after all branch-verifiable requirements pass, validate the OpenSpec change strictly, and confirm candidate/tagged-image verification remains a prepublication requirement.

## 3. Final Gate

- [x] 3.1 Run just check in the devcontainer and fix any failures.

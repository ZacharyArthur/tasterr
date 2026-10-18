# release-readiness Specification (delta)

## MODIFIED Requirements

### Requirement: Deterministic pre-release verification is repeatable

The repository SHALL provide a documented deterministic release command that runs
the ordinary quality gate, the real-backend Playwright smoke, and the native
container/Compose smoke. The release procedure SHALL separately require both locked
dependency audits, the full relevant security checklist, placeholder-only env
verification, and the live Seerr, owner/managed/shared Plex, and Jellyfin
contract suites
because those checks require network access, operator credentials, or human triage.
A failed required check MUST block tagging unless a specific dependency advisory is
risk-triaged in the release record. When retained live credentials have become stale or unavailable,
the release owner MAY explicitly accept a recent complete automated baseline plus a
fresh integrated manual test only for an integration whose request/response path is
unchanged by the release. Every integration changed by the release still requires a
fresh automated pass, and the evidence MUST record any exception without claiming a
fresh automated pass.

#### Scenario: Deterministic release checks pass

- **WHEN** the release command runs in the devcontainer on a release candidate
- **THEN** it exits zero only after `just check`, Playwright E2E, and
  container/Compose smoke all pass

#### Scenario: External release checks remain explicit

- **WHEN** the deterministic command passes without live credentials or registry
  access
- **THEN** the release procedure still shows dependency audits, security/repository
  review, and live Seerr/Plex/Jellyfin contracts as incomplete pre-tag requirements

#### Scenario: V2.3.0 live gate is complete

- **WHEN** the operator reaches the v2.3.0 tag step
- **THEN** mandatory Seerr and owner/managed/shared Plex behavior has either a fresh
  automated pass or, only for an integration unchanged by the release, an explicit
  release-owner exception backed by a complete dated baseline and fresh integrated
  manual test

#### Scenario: V2.2.0 live gate is complete

- **WHEN** the operator reaches the v2.2.0 tag step
- **THEN** mandatory Seerr and owner/managed/shared Plex behavior has either a fresh
  automated pass or, only for an integration unchanged by the release, an explicit
  release-owner exception backed by a complete dated baseline and fresh integrated
  manual test

#### Scenario: V2.1.1 live gate is complete

- **WHEN** the operator reaches the v2.1.1 tag step
- **THEN** mandatory Seerr and owner/managed/shared Plex behavior has either a fresh
  automated pass or, only for an integration unchanged by the release, an explicit
  release-owner exception backed by a complete dated baseline and fresh integrated
  manual test

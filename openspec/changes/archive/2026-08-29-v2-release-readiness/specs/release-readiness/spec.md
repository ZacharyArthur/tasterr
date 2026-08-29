## MODIFIED Requirements

### Requirement: Release-facing documentation is complete and linked

The repository SHALL provide a root quick start plus living configuration,
architecture, releasing, licensing, and vulnerability-reporting documents. The
configuration guide SHALL cover every supported environment variable, secret
generation, existing Seerr networking across routable-LAN and optional same-host
Docker-network paths, loopback-by-default and explicit LAN publication, trusted
proxies/HTTPS, application security headers, private application/proxy logging, first
boot, degraded integration states, named-volume backup and restore, upgrade,
migration-aware rollback, and troubleshooting. The architecture guide SHALL describe
the process/module boundaries, browser/API and upstream data flows, SQLite/cache
lifecycle, generated API types, identity/secrets, and independent Seerr/Plex
degradation without replacing the frozen founding documents. Root and package
metadata SHALL identify the selected AGPL-3.0-only license and the published image
SHALL include its license text. The root quick start SHALL include a copyable Compose
example using the current `2.0.0` GHCR image, loopback host publication, and the named
data volume. It SHALL distinguish Tasterr's ordinary process environment from the
bundled Compose file's explicit environment-file loading and document how another
container platform or Compose service can inject the same variable names without a
file.

#### Scenario: New operator can deploy from living docs

- **WHEN** an operator starts with the root README and an existing Seerr instance
- **THEN** the linked configuration guide contains every required step and variable
  needed to start, expose intentionally, secure, keep logs private, back up, restore,
  upgrade to v2, roll back across migration `0006`, and troubleshoot Tasterr

#### Scenario: Maintainer can locate architectural boundaries

- **WHEN** a maintainer consults the architecture guide
- **THEN** it identifies the enforced `api/`, `clients/`, secret-projection, storage,
  generated-type, and independent Seerr/Plex degradation boundaries without
  requiring a code tour

#### Scenario: License is consistent across release surfaces

- **WHEN** source or a production image is distributed
- **THEN** the root license, package metadata, README, and image identify or include
  AGPL-3.0-only without claiming an unknown repository coordinate

#### Scenario: Published-image Compose is copyable

- **WHEN** an operator deploys the README's published-image Compose example beside a
  populated `.env`
- **THEN** Compose pulls `ghcr.io/zacharyarthur/tasterr:2.0.0`, publishes it on host
  loopback, and persists `/data` in the documented named volume

#### Scenario: Environment sources are unambiguous

- **WHEN** an operator supplies Tasterr configuration through a host service or
  container platform instead of an environment file
- **THEN** the documentation explains that Tasterr accepts ordinary process
  environment variables
- **AND** it explains that Compose requires an explicit `environment` mapping to
  pass host variables into the service when `env_file` is not used

### Requirement: Public vulnerability reporting is private and actionable

The root `SECURITY.md` SHALL identify v2.0.x as the supported stable line, direct
vulnerability reports to GitHub private vulnerability reporting, tell reporters not
to disclose secrets or household data, and describe acknowledgement/remediation
expectations. The release procedure SHALL require private vulnerability reporting,
secret scanning with push protection, Dependabot alerts and updates, immutable
releases, and protected version tags before stable publication.

#### Scenario: Reporter finds a private channel

- **WHEN** a security researcher opens the repository security policy
- **THEN** they are directed to a private reporting path and warned not to open a
  public issue containing exploit details or sensitive data

#### Scenario: Current supported line is clear

- **WHEN** an operator or reporter checks the support table after v2.0 publication
- **THEN** v2.0.x is supported and older or pre-release builds are not

#### Scenario: Public release checks repository security features

- **WHEN** the operator prepares the v2.0 tag
- **THEN** the release checklist requires private reporting, secret scanning,
  dependency maintenance, immutable releases, and protected version tags first

### Requirement: Deterministic pre-release verification is repeatable

The repository SHALL provide a documented deterministic release command that runs
the ordinary quality gate, the real-backend Playwright smoke, and the native
container/Compose smoke. The release procedure SHALL separately require both locked
dependency audits, the full relevant security checklist, placeholder-only env
verification, and the live Seerr plus owner/managed/shared Plex contract suites
because those checks require network access, operator credentials, or human triage.
A failed required check MUST block tagging unless a specific dependency advisory is
risk-triaged in the release record. When retained live credentials have become stale,
the release owner MAY explicitly accept a recent complete automated baseline plus a
fresh integrated manual test only for a release-only delta, and the evidence MUST
record the exception without claiming a fresh automated pass.

#### Scenario: Deterministic release checks pass

- **WHEN** the release command runs in the devcontainer on a release candidate
- **THEN** it exits zero only after `just check`, Playwright E2E, and container/Compose
  smoke all pass

#### Scenario: External release checks remain explicit

- **WHEN** the deterministic command passes without live credentials or registry
  access
- **THEN** the release procedure still shows dependency audits, security/repository
  review, and live Seerr/Plex contracts as incomplete pre-tag requirements

#### Scenario: V2 live gate is complete

- **WHEN** the operator reaches the v2.0 tag step
- **THEN** mandatory Seerr and owner/managed/shared Plex behavior has either a fresh
  automated pass or an explicit release-owner exception backed by a complete dated
  baseline, fresh manual test, and release-only delta

### Requirement: Each release has a redacted evidence record

Before a stable tag is created, the repository SHALL contain a release record naming
the release version/date, deterministic check results, dependency-audit disposition,
security-review scope/result, live Seerr and Plex versions plus generic
exercised/skipped cases, known limitations, and migration-aware rollback basis. The
record MUST NOT contain credentials, tokens, cookies, household identities, request
titles, internal/live URLs, rating keys, server/account identifiers, viewing data,
or raw upstream output. A live case MAY be recorded as skipped only when its
documented data precondition is absent. Merged-candidate and post-tag facts that
cannot exist in the reviewed pre-tag commit SHALL be recorded in the immutable
GitHub Release rather than a post-release source commit.

#### Scenario: V2 evidence is complete before tagging

- **WHEN** the operator reaches the `v2.0.0` tag step
- **THEN** `docs/releases/v2.0.0.md` records every branch-verifiable required outcome,
  tested Seerr/Plex versions, upgrade/rollback basis, limitations, and an approved
  release disposition with no mandatory case unresolved

#### Scenario: v1.0 evidence is complete before tagging

- **WHEN** the operator reaches the v1.0 tag step
- **THEN** `docs/releases/v1.0.0.md` records all required outcomes and the tested
  Seerr version with no mandatory case unresolved

#### Scenario: Evidence remains safe to publish

- **WHEN** the release record or GitHub Release is reviewed or published
- **THEN** it contains outcomes, versions, generic limitations, manifests, and
  digests only, with none of the prohibited secret or household-specific material

#### Scenario: Post-tag facts do not advance main

- **WHEN** stable aliases, final digest, attestation, and tagged-image smoke are
  known after the immutable tag exists
- **THEN** they are recorded in the immutable GitHub Release without a source commit
  that would create a different candidate image

### Requirement: Stable versioning and release order are explicit

The Plex-aware major release SHALL use SemVer `2.0.0` in backend/frontend package and
lock metadata and Git tag `v2.0.0`. Its release-readiness change and living specs
SHALL be archived and squash-merged through required `check`, `e2e`,
`container-smoke`, and CodeQL gates before tagging. The main workflow SHALL publish
an immutable commit-SHA candidate with verifiable provenance. Before the stable tag,
the release procedure SHALL verify that candidate's amd64/arm64 manifest, artifact
attestation, public package visibility, anonymous pull, clean deployment, non-root
runtime, health, SPA, and named-volume persistence. The tag workflow SHALL publish
`2.0.0`, `2.0`, `2`, and `latest` while leaving the SHA candidate unchanged; those
stable aliases, their attestation, and a fresh tagged deployment SHALL be verified
before the immutable GitHub Release. Rollback SHALL use an immutable prior image
digest plus either the documented `0006` to `0005` downgrade performed with the v2
image or a validated pre-upgrade SQLite backup. Every template owner/repository
marker MUST be replaced by the final coordinate before publication.

#### Scenario: Stable tag follows the atomic merge

- **WHEN** the v2 release-readiness change has passed review and been squash-merged
- **THEN** the operator tags that releasable main commit `v2.0.0`, not an unmerged
  change-branch commit

#### Scenario: First stable tag follows the atomic merge

- **WHEN** the v1 public-release-readiness change has passed its release checks and
  been squash-merged
- **THEN** the operator tags that releasable main commit `v1.0.0`, not an unmerged
  change-branch commit

#### Scenario: Publication placeholders are resolved

- **WHEN** the operator creates or announces the public repository
- **THEN** README, release instructions, license/source references, and image commands
  use the actual owner/repository coordinate

#### Scenario: Bootstrap does not publish the old main branch

- **WHEN** the operator imports the existing base and reviewed change branches into
  the new private repository
- **THEN** Actions remains disabled until both branches exist and the release change
  can enter the documented gated pull-request flow

#### Scenario: Candidate precedes the stable tag

- **WHEN** the release-readiness change is merged and the main workflow publishes
  its immutable SHA candidate
- **THEN** the operator verifies both architectures, attestation, public visibility,
  anonymous pull, and a disposable clean installation before creating `v2.0.0`

#### Scenario: Public candidate precedes the stable tag

- **WHEN** the readiness change is squash-merged and the main workflow publishes its
  immutable candidate
- **THEN** the operator verifies both architectures, public package visibility, and
  a clean anonymous installation before creating `v1.0.0`

#### Scenario: Published image is verified

- **WHEN** the stable image workflow finishes for `v2.0.0`
- **THEN** the operator confirms `2.0.0`, `2.0`, `2`, `latest`, and the unchanged SHA
  candidate resolve to the release commit, verifies the stable manifest and
  attestation, and completes a fresh tagged-image deployment before publishing the
  immutable GitHub Release

#### Scenario: Failed publication fixes forward

- **WHEN** any verification fails after `v2.0.0` is published
- **THEN** the tag is never moved, deleted, or reused and remediation ships through
  protected main as the next patch release

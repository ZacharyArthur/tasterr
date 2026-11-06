## MODIFIED Requirements

### Requirement: Release-facing documentation is complete and linked

The repository SHALL provide a root quick start plus living configuration,
architecture, releasing, licensing, and vulnerability-reporting documents.

#### Details

Root and package metadata SHALL identify AGPL-3.0-only and the published image
SHALL include its license text. The root quick start SHALL include a copyable
Compose example using the current `2.4.0` GHCR image, loopback host publication,
and the named data volume.

#### Scenario: New operator can deploy from living docs

- **WHEN** an operator starts with the root README and an existing Seerr instance
- **THEN** the linked configuration guide contains every required step and variable
  needed to start, expose intentionally, secure, keep logs private, back up, restore,
  upgrade to v2.4.0, roll back across migrations `0010`–`0007` to v2.3.1 or
  migration `0006` to v1.1, and troubleshoot Tasterr

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
- **THEN** Compose pulls `ghcr.io/zacharyarthur/tasterr:2.4.0`, publishes it on host
  loopback, and persists `/data` in the documented named volume

#### Scenario: Environment sources are unambiguous

- **WHEN** an operator supplies Tasterr configuration through a host service or
  container platform instead of an environment file
- **THEN** the documentation explains that Tasterr accepts ordinary process
  environment variables
- **AND** it explains that Compose requires an explicit `environment` mapping to
  pass host variables into the service when `env_file` is not used

### Requirement: Public vulnerability reporting is private and actionable

The root `SECURITY.md` SHALL identify v2.4.x as the supported stable line, direct
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

- **WHEN** an operator or reporter checks the support table after v2.4 publication
- **THEN** v2.4.x is supported and older or pre-release builds are not

#### Scenario: Public release checks repository security features

- **WHEN** the operator prepares the v2.4.0 tag
- **THEN** the release checklist requires private reporting, secret scanning,
  dependency maintenance, immutable releases, and protected version tags first

### Requirement: Deterministic pre-release verification is repeatable

The repository SHALL provide a documented deterministic release command that runs
the ordinary quality gate, the real-backend Playwright smoke, and the native
container/Compose smoke.

#### Details

External checks remain separate from the deterministic release command.

#### Scenario: Deterministic release checks pass

- **WHEN** the release command runs in the devcontainer on a release candidate
- **THEN** it exits zero only after `just check`, Playwright E2E, and
  container/Compose smoke all pass

#### Scenario: External release checks remain explicit

- **WHEN** the deterministic command passes without live credentials or registry
  access
- **THEN** the release procedure still shows dependency audits, security/repository
  review, and live Seerr/Plex/Jellyfin/Trakt contracts as incomplete pre-tag requirements

#### Scenario: V2.4.0 live gate is complete

- **WHEN** the operator reaches the v2.4.0 tag step
- **THEN** mandatory Seerr, owner/managed/shared Plex, Jellyfin and Trakt behavior
  has a fresh automated pass, including every integration changed by the release
- **AND** only documented absent-data cases skip, with generic evidence

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

### Requirement: Each release has a redacted evidence record

Before a stable tag is created, the repository SHALL contain a release record naming
the release version/date, deterministic check results, dependency-audit disposition,
security-review scope/result, live Seerr/Plex/Jellyfin versions and Trakt API version plus generic
exercised/skipped cases, known limitations, and migration-aware rollback basis.

#### Details

A live case MAY be recorded as skipped only when its documented data
precondition is absent.

#### Scenario: V2.4.0 evidence is complete before tagging

- **WHEN** the operator reaches the `v2.4.0` tag step
- **THEN** `docs/releases/v2.4.0.md` records every branch-verifiable required outcome,
  tested Seerr/Plex/Jellyfin versions and Trakt API version, upgrade/rollback basis,
  limitations and an approved disposition with no mandatory case unresolved

#### Scenario: V2.3.0 evidence is complete before tagging

- **WHEN** the operator reaches the `v2.3.0` tag step
- **THEN** `docs/releases/v2.3.0.md` records every branch-verifiable required outcome,
  tested Seerr/Plex versions, upgrade/rollback basis, limitations, and an approved
  release disposition with no mandatory case unresolved

#### Scenario: V2.2.0 evidence is complete before tagging

- **WHEN** the operator reaches the `v2.2.0` tag step
- **THEN** `docs/releases/v2.2.0.md` records every branch-verifiable required outcome,
  tested Seerr/Plex versions, upgrade/rollback basis, limitations, and an approved
  release disposition with no mandatory case unresolved

#### Scenario: V2.1.1 evidence is complete before tagging

- **WHEN** the operator reaches the `v2.1.1` tag step
- **THEN** `docs/releases/v2.1.1.md` records every branch-verifiable required outcome,
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

- **WHEN** stable aliases, final digest, attestation, and tagged-image smoke are known
  after the immutable tag exists
- **THEN** they are recorded in the immutable GitHub Release without a source commit
  that would create a different candidate image

### Requirement: Stable versioning and release order are explicit

The current stable release SHALL use SemVer `2.4.0` in backend/frontend package and
lock metadata and Git tag `v2.4.0`.

#### Details

The tag workflow SHALL publish `2.4.0`, `2.4`, `2`, and `latest` while leaving
the SHA candidate unchanged. Every template owner/repository marker MUST be
replaced by the final coordinate before publication.

#### Scenario: Stable tag follows the atomic merge

- **WHEN** the v2.4.0 release preparation has passed review and been squash-merged
- **THEN** the operator tags that releasable main commit `v2.4.0`, not an unmerged
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

- **WHEN** the release-readiness change is merged and the main workflow publishes its
  immutable candidate
- **THEN** the operator verifies both architectures, attestation, public visibility,
  anonymous pull, and a disposable clean installation before creating `v2.4.0`

#### Scenario: Public candidate precedes the stable tag

- **WHEN** the readiness change is squash-merged and the main workflow publishes its
  immutable candidate
- **THEN** the operator verifies both architectures, public package visibility, and
  a clean anonymous installation before creating `v1.0.0`

#### Scenario: Published image is verified

- **WHEN** the stable image workflow finishes for `v2.4.0`
- **THEN** the operator confirms `2.4.0`, `2.4`, `2`, `latest`, and the unchanged SHA
  candidate resolve to the release commit, verifies the stable manifest and
  attestation, and completes a fresh tagged-image deployment before publishing the
  immutable GitHub Release

#### Scenario: Failed publication fixes forward

- **WHEN** any verification fails after `v2.4.0` is published
- **THEN** the tag is never moved, deleted, or reused and remediation ships through
  protected main as the next patch release

## ADDED Requirements

### Requirement: Operator configuration guidance covers deployment and recovery

The configuration guide SHALL document every supported environment variable, secret
generation, routable-LAN and optional same-host Seerr networking, loopback defaults
and intentional LAN publication, trusted proxies/HTTPS, security headers, private
application/proxy logging, first boot, degraded integrations, named-volume backup
and restore, upgrades, migration-aware rollback and troubleshooting.

#### Scenario: Operator can recover a deployment

- **WHEN** an operator upgrades or restores a deployment
- **THEN** the guide provides stopped-writer validated backups, migration-aware
  rollback and generic troubleshooting without exposing household data

### Requirement: Architecture and environment boundaries are documented

The architecture guide SHALL describe module boundaries, browser/API and upstream
flows, SQLite/cache lifecycle, generated types, identity/secrets and independent
Seerr/Plex degradation without replacing the frozen founding documents.
Documentation SHALL distinguish ordinary process environment from Compose's
explicit environment-file loading and explain injecting the same names without a
file, including explicit Compose environment mappings.

#### Scenario: Maintainer can distinguish configuration sources

- **WHEN** a maintainer moves deployment to another container platform
- **THEN** the architecture and configuration guides explain boundaries and
  supplying the same process variables without requiring an environment file

### Requirement: External release verification remains mandatory

The release procedure SHALL separately require both locked dependency audits,
the full relevant security checklist, placeholder-only environment verification,
repository controls and live Seerr, owner/managed/shared Plex, Jellyfin and Trakt
contract suites. A failed required check MUST block tagging unless a specific
dependency advisory is risk-triaged in the release record.

#### Scenario: Deterministic success cannot substitute for external evidence

- **WHEN** deterministic checks pass but a mandatory external check is unresolved
- **THEN** tagging remains blocked until it passes or a permitted advisory
  disposition or unchanged-integration exception is recorded

### Requirement: Live exceptions require unchanged integration paths

When retained live credentials become stale or unavailable, the release owner MAY
explicitly accept a recent complete automated baseline plus a fresh integrated
manual test only for an integration whose request/response path is unchanged by the
release. Every changed integration SHALL have a fresh automated pass. Evidence MUST
record each exception without claiming a fresh automated pass.

#### Scenario: Changed integration cannot reuse an old baseline

- **WHEN** a release changes an integration's request/response path
- **THEN** a fresh automated live pass is required even if an older complete
  baseline or a fresh manual test exists

### Requirement: Release evidence protects private data and source history

Release records MUST exclude credentials, tokens, cookies, household identities,
request titles, internal/live URLs, rating keys, server/account identifiers,
viewing data and raw upstream output. Merged-candidate and post-tag facts that
cannot exist in the reviewed pre-tag commit SHALL be recorded in the immutable
GitHub Release without a post-release source commit.

#### Scenario: Candidate facts are recorded after merge

- **WHEN** a merged candidate digest or post-tag verification becomes available
- **THEN** it is recorded in the GitHub Release with generic results and no
  private material or extra source commit

### Requirement: Candidate verification follows protected-main merge

Release preparation and applicable archived changes SHALL be squash-merged through
required check, e2e, container-smoke and CodeQL gates before tagging. The main
workflow SHALL publish an immutable commit-SHA candidate with verifiable provenance.
Before tagging, verify its amd64/arm64 manifest, attestation, public package
visibility, anonymous pull, clean deployment, non-root runtime, health, SPA and
named-volume persistence.

#### Scenario: Candidate must be verified before tagging

- **WHEN** protected main publishes a release candidate
- **THEN** every listed candidate check passes and disposable resources are
  removed before the stable tag is created

### Requirement: Stable aliases are verified before immutable publication

Before the immutable GitHub Release, the release procedure SHALL verify that
`2.4.0`, `2.4`, `2` and `latest` resolve to the release commit, the SHA candidate
retains its recorded digest, and the stable manifest, artifact attestation and
fresh tagged deployment pass.

#### Scenario: Tagged image is verified separately

- **WHEN** the stable image workflow finishes
- **THEN** stable aliases, manifest, attestation and a disposable fresh install
  pass without replacing the previously verified SHA candidate

### Requirement: Rollback respects the prior release schema

Immediate rollback from v2.4.0 SHALL target the immutable v2.3.1 digest only after
restoring a validated matching backup or downgrading with the current image through
`0010` → `0009` → `0008` → `0007` → `0006`, documenting all destructive limits.
Rollback across migration `0006` to v1.1 SHALL first downgrade to `0005` with a v2
image or restore a validated matching pre-upgrade backup.

#### Scenario: Previous stable image never opens the new schema

- **WHEN** an operator rolls back v2.4.0 to v2.3.1
- **THEN** the writer is stopped and the documented backup or downgrade procedure
  reaches revision `0006` before the old image starts
- **AND** warnings cover Trakt/Jellyfin links and history, source preferences,
  users without Seerr, their local data and every session

### Requirement: SemVer covers supported operator contracts

SemVer SHALL cover configuration/environment variables, the image and its tags,
the health endpoint, persisted data and upgrade/downgrade paths, and documented
operator procedures. The bundled SPA's private `/api/v1` backend SHALL be versioned
with its frontend and excluded from supported SemVer integration contracts.

#### Scenario: Internal response change ships with its only client

- **WHEN** a private SPA response changes with the bundled frontend while
  supported operator contracts remain compatible
- **THEN** the internal change alone does not require a major release

#### Scenario: Operator contract incompatibility requires a major release

- **WHEN** a supported operator contract breaks or a manual migration is required
- **THEN** the release uses a new major version

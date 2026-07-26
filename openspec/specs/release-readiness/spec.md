# release-readiness Specification

## Purpose
TBD - created by archiving change m6-hardening-release. Update Purpose after archive.
## Requirements
### Requirement: Release-facing documentation is complete and linked

The repository SHALL provide a root quick start plus living configuration,
architecture, releasing, licensing, and vulnerability-reporting documents. The
configuration guide SHALL cover every supported environment variable, secret
generation, existing Seerr networking across routable-LAN and optional same-host
Docker-network paths, loopback-by-default and explicit LAN publication, trusted
proxies/HTTPS, application security headers, private application/proxy logging, first
boot, degraded integration states, named-volume backup and restore, upgrade,
rollback, and troubleshooting. The architecture guide SHALL describe the process/
module boundaries, browser/API and upstream data flows, SQLite/cache lifecycle,
generated API types, identity/secrets, and Seerr degradation without replacing the
frozen founding documents. Root and package metadata SHALL identify the selected
AGPL-3.0-only license and the published image SHALL include its license text. The
root quick start SHALL include a copyable Compose example that uses the selected
versioned GHCR image, loopback host publication, and the named data volume. It SHALL
distinguish Tasterr's ordinary process environment from the bundled Compose file's
explicit environment-file loading and document how another container platform or
Compose service can inject the same variable names without a file.

#### Scenario: New operator can deploy from living docs

- **WHEN** an operator starts with the root README and an existing Seerr instance
- **THEN** the linked configuration guide contains every required step and variable
  needed to start, expose intentionally, secure, keep logs private, back up, restore,
  upgrade, and troubleshoot Tasterr

#### Scenario: Maintainer can locate architectural boundaries

- **WHEN** a maintainer consults the architecture guide
- **THEN** it identifies the enforced `api/`, `clients/`, secret-projection, storage,
  generated-type, and Seerr-degradation boundaries without requiring a code tour

#### Scenario: License is consistent across release surfaces

- **WHEN** source or a production image is distributed
- **THEN** the root license, package metadata, README, and image identify or include
  AGPL-3.0-only without claiming an unknown repository coordinate

#### Scenario: Published-image Compose is copyable

- **WHEN** an operator deploys the README's published-image Compose example beside a
  populated `.env`
- **THEN** Compose pulls the selected versioned GHCR image, publishes it on host
  loopback, and persists `/data` in the documented named volume

#### Scenario: Environment sources are unambiguous

- **WHEN** an operator supplies Tasterr configuration through a host service or
  container platform instead of an environment file
- **THEN** the documentation explains that Tasterr accepts ordinary process
  environment variables
- **AND** it explains that Compose requires an explicit `environment` mapping to
  pass host variables into the service when `env_file` is not used

### Requirement: Public vulnerability reporting is private and actionable

The root `SECURITY.md` SHALL state the supported release line, direct vulnerability
reports to GitHub private vulnerability reporting, tell reporters not to disclose
secrets or household data, and describe the acknowledgement/remediation expectations.
The release procedure SHALL require private vulnerability reporting, secret scanning,
and Dependabot alerts to be enabled before a public repository or package is
announced.

#### Scenario: Reporter finds a private channel
- **WHEN** a security researcher opens the repository security policy
- **THEN** they are directed to a private reporting path and warned not to open a
  public issue containing exploit details or sensitive data

#### Scenario: Public release checks repository security features
- **WHEN** the operator prepares to make the repository or package public
- **THEN** the release checklist requires private reporting, secret scanning, and
  dependency alerts to be enabled first

### Requirement: Deterministic pre-release verification is repeatable

The repository SHALL provide a documented deterministic release command that runs
the ordinary quality gate, the real-backend Playwright smoke, and the native
container/Compose smoke. The release procedure SHALL separately require dependency
audits, the full relevant security checklist, placeholder-only env verification, and
the live Seerr contract suite because those checks require network access, operator
credentials, or human triage. A failed required check MUST block tagging unless a
specific audit finding is risk-triaged in the release record.

#### Scenario: Deterministic release checks pass
- **WHEN** the release command runs in the devcontainer on a release candidate
- **THEN** it exits zero only after `just check`, Playwright E2E, and container/Compose
  smoke all pass

#### Scenario: External release checks remain explicit
- **WHEN** the deterministic command passes without live credentials or registry
  access
- **THEN** the release procedure still shows dependency audit, security review, and
  live Seerr contracts as incomplete pre-tag requirements

### Requirement: Each release has a redacted evidence record

Before a stable tag is created, the repository SHALL contain a release record naming
the release version/date, deterministic check results, dependency-audit disposition,
security-review scope/result, live Seerr version and exercised/skipped cases, known
limitations, and rollback basis. The record MUST NOT contain credentials, tokens,
cookies, household identities, request titles, internal/live URLs, or other private
viewing data. A live case MAY be recorded as skipped only when its documented data
precondition is absent; the stored-Plex-token authentication contract MUST pass for
v1.0.

#### Scenario: v1.0 evidence is complete before tagging
- **WHEN** the operator reaches the v1.0 tag step
- **THEN** `docs/releases/v1.0.0.md` records all required outcomes and the tested
  Seerr version with no mandatory case unresolved

#### Scenario: Evidence remains safe to publish
- **WHEN** the release record is reviewed or published
- **THEN** it contains outcomes, versions, and generic limitations only, with none of
  the prohibited secret or household-specific material

### Requirement: Stable versioning and release order are explicit

The first stable release SHALL use SemVer `1.0.0` in package metadata and Git tag
`v1.0.0`. The readiness change's code and living specs SHALL be archived and merged
atomically before the operator creates the tag. Before repository creation or public
announcement, every template owner/repository marker MUST be replaced by the final
coordinate. The first repository bootstrap SHALL begin with an empty public
repository and Actions disabled while the existing base and reviewed change branches
are imported. The readiness change SHALL merge through the required `check`, `e2e`,
and `container-smoke` pull-request gates before the main workflow publishes an
immutable candidate. The release procedure SHALL verify that candidate's
multi-architecture manifest, public package visibility, and anonymous clean
installation before creating the stable tag. It SHALL verify the tagged image's
`1.0.0`, `1.0`, `1`, `latest`, and immutable SHA tags and fresh deployment before
the GitHub Release, and SHALL document rollback by immutable image digest and
validated SQLite backup.

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

#### Scenario: Public candidate precedes the stable tag

- **WHEN** the readiness change is squash-merged and the main workflow publishes its
  immutable candidate
- **THEN** the operator verifies both architectures, public package visibility, and
  a clean anonymous installation before creating `v1.0.0`

#### Scenario: Published image is verified

- **WHEN** the stable image workflow finishes for `v1.0.0`
- **THEN** the operator confirms every documented stable and immutable tag, verifies
  amd64 and arm64 manifests, and completes a fresh-start smoke from the tagged GHCR
  image before publishing the GitHub Release

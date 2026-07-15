# container-deploy Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.
## Requirements
### Requirement: Multi-stage image serves the full app
The Dockerfile SHALL build in two stages — node builds the SPA, a python:3.13-slim
stage installs the backend with uv and serves both `/api/v1/*` and the SPA. The
runtime MUST run as a non-root user and define a healthcheck against
`/api/v1/health`. No secrets may appear in image layers or build args.

#### Scenario: Container serves API and SPA
- **WHEN** the built image runs with a valid env file
- **THEN** `/api/v1/health` returns 200, the SPA is served at `/`, the process runs
  as non-root, and the container reports healthy

### Requirement: Compose example wires the stack
`docker-compose.yml` SHALL start Tasterr on a Compose-managed network and reach an
existing Seerr exclusively through `SEERR_INTERNAL_URL`, without requiring a
pre-created external network. A separate optional override SHALL let Tasterr join an
operator-named external network when Seerr runs on the same Docker host in another
Compose project and service-name discovery is desired. The base example SHALL keep
the optional Seerr service commented out rather than start a second server by
default, and SHALL store the SQLite file on a named volume.

#### Scenario: Compose brings the app up
- **WHEN** `docker compose up` runs with the base example and a populated `.env`
- **THEN** Tasterr starts on its managed network, persists its database on the named
  volume, and passes its healthcheck

#### Scenario: Routable Seerr needs no external network
- **WHEN** `docker compose up` runs with a populated `.env` whose internal URL points
  to a Seerr instance reachable through LAN routing or DNS
- **THEN** Tasterr starts, persists its database on the named volume, reaches Seerr
  through the internal URL, and passes its healthcheck without an operator-managed
  Docker network

#### Scenario: Same-host cross-stack discovery is opt-in
- **WHEN** the operator supplies `TASTERR_MEDIA_NETWORK` and includes
  `docker-compose.seerr-network.yml`
- **THEN** Tasterr joins that existing external network and can resolve the Seerr
  service name or alias without changing the base deployment path

#### Scenario: Example does not create an unsolicited Seerr
- **WHEN** an operator uses the compose file without uncommenting the optional Seerr
  block
- **THEN** Compose starts Tasterr only and leaves the household's existing Seerr
  lifecycle untouched

### Requirement: Env example is complete and placeholder-only
`.env.example` SHALL list every environment variable the app reads, with
placeholder values only — no real keys, hostnames, or paths from any live system.

#### Scenario: New deploy starts from the example
- **WHEN** a user copies `.env.example` to `.env` and fills in real values
- **THEN** the app boots with no undocumented variable required

### Requirement: Production image and Compose contracts are smoke-tested

The repository SHALL provide one automated native container smoke that builds the
production Dockerfile and starts an isolated Compose project with placeholder-only
configuration. It SHALL verify health, SPA serving, non-root execution, SQLite file
creation, and named-volume persistence across forced container recreation. The smoke
MUST clean up its isolated containers, network, image tag, and volume on success or
failure, and MUST NOT read or print a real `.env` or integration secret.

#### Scenario: Native image satisfies its runtime contract
- **WHEN** the container smoke runs on a clean Docker host
- **THEN** the image builds, becomes healthy, serves `/api/v1/health` and `/`, and
  reports a non-zero runtime uid

#### Scenario: Compose recreation preserves SQLite data
- **WHEN** the smoke writes a marker into the disposable `/data/tasterr.db`, forcibly
  recreates the Tasterr container, and queries the same named volume
- **THEN** the marker is still present after recreation

#### Scenario: Smoke never consumes deployment secrets
- **WHEN** the container smoke runs in local development or CI
- **THEN** it uses generated placeholder/unconfigured values and removes all isolated
  Docker resources even if an assertion fails

### Requirement: GHCR publishes a tagged multi-architecture image

A GitHub Actions image workflow SHALL run the native container smoke before using
Buildx to publish the production image for `linux/amd64` and `linux/arm64` to
`ghcr.io/${{ github.repository }}` on pushes to `main` and stable `v*` tags. Every
publish SHALL include an immutable commit tag; `main` SHALL update a moving main tag;
a stable SemVer tag SHALL publish full/major-minor/major tags and update `latest`.
The workflow MUST use least-privilege package permissions, immutable third-party
action pins, and no secret-bearing build args or image layers.

#### Scenario: Main publishes both architectures
- **WHEN** a verified commit reaches `main`
- **THEN** GHCR receives amd64 and arm64 manifests under the main and immutable commit
  tags

#### Scenario: Stable tag publishes SemVer aliases
- **WHEN** the operator pushes `v1.0.0` on the releasable main commit
- **THEN** GHCR receives `1.0.0`, `1.0`, `1`, `latest`, and the immutable commit tag,
  all referring to the multi-architecture image

#### Scenario: Failed native smoke blocks publication
- **WHEN** the health, SPA, uid, or persistence smoke fails
- **THEN** the workflow exits non-zero before logging in and publishing a new image


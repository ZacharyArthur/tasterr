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
A `docker-compose.yml` SHALL show Tasterr beside Seerr on a shared network
(`SEERR_INTERNAL_URL=http://seerr:5055`-style) with the SQLite file on a named volume.

#### Scenario: Compose brings the app up
- **WHEN** `docker compose up` runs with the example file and a populated `.env`
- **THEN** Tasterr starts, persists its database on the named volume, and passes
  its healthcheck

### Requirement: Env example is complete and placeholder-only
`.env.example` SHALL list every environment variable the app reads, with
placeholder values only — no real keys, hostnames, or paths from any live system.

#### Scenario: New deploy starts from the example
- **WHEN** a user copies `.env.example` to `.env` and fills in real values
- **THEN** the app boots with no undocumented variable required


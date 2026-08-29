# dev-tooling Specification

## Purpose
TBD - created by archiving change m0-scaffold. Update Purpose after archive.
## Requirements
### Requirement: Single quality gate command
The repo SHALL provide a root `justfile` where `just check` runs the full quality
gate: ruff lint + format check, pyright (strict) and pytest on the backend, and
Biome check, TypeScript typecheck, Vitest, and a production build on the frontend.
`just check` MUST exit non-zero if any step fails.

#### Scenario: Gate passes on a clean tree
- **WHEN** `just check` runs on a tree where all checks pass
- **THEN** it exits 0 after running every backend and frontend check

#### Scenario: Gate fails on any broken step
- **WHEN** any single step (e.g. a type error, a failing test) fails
- **THEN** `just check` exits non-zero

### Requirement: CI runs the identical gate on PRs
A GitHub Actions workflow SHALL run `just check` — the same command, not a
re-implementation — on every pull request.

#### Scenario: PR triggers the gate
- **WHEN** a pull request is opened or updated
- **THEN** CI runs `just check` and the PR is blocked if it fails

### Requirement: Boundary invariants are mechanically enforced
The gate SHALL include import-linter contracts asserting that only
`tasterr.clients` may import `httpx`, that `tasterr.api` is not imported by
domain or client modules, and that the **catalog and rails domain-model modules**
(the network-free typed shapes those layers build) do not import the application
settings module — so secret configuration can never be embedded in them. (`api/`
routers legitimately import settings for dependency injection; the client-facing
guarantee there is upheld by an explicit `response_model` on every route plus the
PublicConfig no-secrets regression test.)

#### Scenario: httpx import outside clients/ fails the gate
- **WHEN** a module outside `tasterr.clients` imports `httpx`
- **THEN** the import-linter step fails and `just check` exits non-zero

#### Scenario: settings import from a domain model fails the gate
- **WHEN** a catalog or rails domain-model module imports the application settings module
- **THEN** the import-linter step fails and `just check` exits non-zero

### Requirement: Frontend API types are generated from OpenAPI
Frontend API request/response types SHALL be generated from the backend's OpenAPI
schema via a `just` recipe, never hand-written a second time. The quality gate
SHALL verify that the committed generated types match what the current schema
produces, failing when they have drifted out of sync.

#### Scenario: Types regenerate from the schema
- **WHEN** the type-generation recipe runs
- **THEN** the frontend's API types file is produced from the backend OpenAPI schema
  and the frontend typechecks against it

#### Scenario: Stale generated types fail the gate
- **WHEN** the backend schema has changed but the committed generated types were
  not regenerated
- **THEN** the gate's freshness check fails and `just check` exits non-zero

### Requirement: Devcontainer runs the gate without host dependencies
The repo SHALL provide a `.devcontainer/` configuration that supplies the full
toolchain (uv, node, just, GitHub CLI, OpenSpec) in a Linux container with the
repository bind-mounted from the local working copy. Dependency trees (`backend/.venv`,
`frontend/node_modules`) MUST live on container volumes, not the host filesystem.
`just check` inside the devcontainer MUST be the same command and gate as on the
host and in CI.

#### Scenario: Gate runs inside the devcontainer
- **WHEN** the devcontainer is created and `just check` runs inside it
- **THEN** the full gate executes with no toolchain installed on the host, and
  edits made in the container appear in the local working copy

### Requirement: Dependency audit command
The repo SHALL provide `just audit` running pip-audit and npm audit as a
non-blocking advisory, and lockfiles (`uv.lock`, `package-lock.json`) MUST be
committed.

#### Scenario: Audit reports without blocking
- **WHEN** `just audit` runs and a dependency advisory exists
- **THEN** findings are reported but the command is advisory (not part of `just check`)

### Requirement: Playwright smoke drives a real backend deterministically

The repository SHALL provide a lightweight Chromium Playwright suite that serves the
compiled SPA from a real Tasterr FastAPI process using a temporary SQLite database
and deterministic local TMDB/Seerr doubles. The smoke SHALL cover local login, home
browsing, opening detail, and requesting a title through visible user behavior. It
MUST use only invented fixture data and placeholder credentials, make no live
internet request, add no production test mode, and retain diagnostic artifacts only
on failure.

#### Scenario: Browser completes the v1.0 critical journey
- **WHEN** `just e2e` runs in the devcontainer with Chromium installed
- **THEN** the compiled SPA logs in through the real backend, renders home, opens a
  detail view, submits a request, and displays the resulting success state

#### Scenario: E2E is hermetic
- **WHEN** the Playwright smoke runs without TMDB, Seerr, or Plex credentials and
  without internet access
- **THEN** it completes against local typed upstream doubles and a disposable
  database without reading a real `.env`

### Requirement: Deterministic release checks have one command

The root `justfile` SHALL provide `just release-check` that runs `just check`,
`just e2e`, and `just container-smoke` sequentially and exits non-zero on any failure.
It SHALL NOT silently include live Seerr tests or dependency audits, which remain
explicit documented release steps because they require operator credentials,
network access, or finding triage.

#### Scenario: Release check propagates every deterministic failure
- **WHEN** any ordinary gate, browser smoke, or container smoke assertion fails
- **THEN** `just release-check` exits non-zero and the release is not ready to tag

#### Scenario: Passing command does not imply external checks ran
- **WHEN** `just release-check` exits zero
- **THEN** the release documentation still requires separate audit, security-review,
  and live-contract evidence before tagging

### Requirement: PR CI blocks on browser and container smoke

The pull-request workflow SHALL keep running the identical `just check` command and
SHALL add separate blocking jobs for `just e2e` and `just container-smoke`. The E2E
job SHALL install only its pinned Chromium browser/tooling, and both jobs SHALL use
the same checked-in commands developers run in the devcontainer.

#### Scenario: Pull request exercises release paths
- **WHEN** a pull request is opened or updated
- **THEN** CI runs the ordinary gate, the real-backend browser smoke, and the native
  container/Compose smoke as blocking checks

#### Scenario: Local and CI smoke commands do not diverge
- **WHEN** a smoke fails in CI
- **THEN** a maintainer can reproduce it in the devcontainer with the same `just e2e`
  or `just container-smoke` command

### Requirement: GitHub Actions are least-privilege and immutably pinned

Every third-party action used by the gate and image workflows SHALL be referenced by
a full immutable commit SHA with a human-readable release-version comment. Workflow
permissions SHALL default to read-only and grant write access only to the image
publish job's package scope. Pull-request jobs MUST NOT receive package-write
credentials or publish images.

#### Scenario: Action tag cannot move underneath CI
- **WHEN** a third-party action release tag is retargeted upstream
- **THEN** Tasterr workflows continue executing the reviewed immutable action commit

#### Scenario: Pull request cannot publish a package
- **WHEN** untrusted pull-request code executes in CI
- **THEN** its workflow token has no package-write permission and no publish step runs

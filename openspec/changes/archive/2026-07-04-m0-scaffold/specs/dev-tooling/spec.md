# dev-tooling

## ADDED Requirements

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
`tasterr.clients` may import `httpx`, and that `tasterr.api` is not imported by
domain or client modules.

#### Scenario: httpx import outside clients/ fails the gate
- **WHEN** a module outside `tasterr.clients` imports `httpx`
- **THEN** the import-linter step fails and `just check` exits non-zero

### Requirement: Frontend API types are generated from OpenAPI
Frontend API request/response types SHALL be generated from the backend's OpenAPI
schema via a `just` recipe, never hand-written a second time.

#### Scenario: Types regenerate from the schema
- **WHEN** the type-generation recipe runs
- **THEN** the frontend's API types file is produced from the backend OpenAPI schema
  and the frontend typechecks against it

### Requirement: Devcontainer runs the gate without host dependencies
The repo SHALL provide a `.devcontainer/` configuration that supplies the full
toolchain (uv, node, just) in a Linux container with the repository bind-mounted
from the local working copy. Dependency trees (`backend/.venv`,
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

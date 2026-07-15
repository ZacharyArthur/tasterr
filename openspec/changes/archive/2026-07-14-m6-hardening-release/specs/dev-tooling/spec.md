## ADDED Requirements

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

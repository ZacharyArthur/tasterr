## MODIFIED Requirements

### Requirement: GitHub Actions are least-privilege and immutably pinned

Every third-party action used by the gate, image and CodeQL workflows SHALL be referenced by
a full immutable commit SHA with a human-readable release-version comment. Workflow
permissions SHALL default to read-only and grant write access only to the image
publish job's package scope and CodeQL analysis jobs' security-events scope. Pull-request jobs MUST NOT receive package-write
credentials or publish images.

#### Scenario: Action tag cannot move underneath CI
- **WHEN** a third-party action release tag is retargeted upstream
- **THEN** Tasterr workflows continue executing the reviewed immutable action commit

#### Scenario: Pull request cannot publish a package
- **WHEN** untrusted pull-request code executes in CI
- **THEN** its workflow token has no package-write permission and no publish step runs

## ADDED Requirements

### Requirement: CodeQL scans fork pull requests

The repository SHALL provide an advanced CodeQL workflow that scans Actions,
JavaScript/TypeScript and Python on every pull request to main, including forks,
on main pushes and weekly. It SHALL use the default query suite on standard
GitHub-hosted runners, bounded runtime and immutable action pins. Pull-request
analysis SHALL use pull_request rather than a privileged target event and SHALL
NOT execute project build scripts, receive secrets or publish packages. The
native CodeQL result SHALL remain a required merge check. GitHub default setup
SHALL be disabled when the advanced workflow is published so uploads can run.

#### Scenario: Contributor fork receives the required scan

- **WHEN** a fork pull request targets main
- **THEN** its code is analyzed and the native CodeQL result is available for merge protection

#### Scenario: Analysis has only its required write permission

- **WHEN** CodeQL runs on PR code
- **THEN** only security analysis upload permission is requested, with no package-write or publish step

#### Scenario: Main and weekly scans preserve coverage

- **WHEN** main changes or the weekly schedule runs
- **THEN** the same three-language default-query scan executes on standard runners

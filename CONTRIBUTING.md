# Contributing to Tasterr

Thanks for helping improve Tasterr. Small, focused changes are the easiest to review
and maintain. Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- Search existing issues before opening a new one.
- Use the [issue chooser](https://github.com/ZacharyArthur/tasterr/issues/new/choose)
  for bug reports and feature requests.
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
- For substantial changes, consider opening a feature request to discuss scope
  before investing in implementation. Prior discussion is encouraged, but is not
  required to begin work or open a pull request.

## Development environment

All development and checks run inside the repository's devcontainer. Docker is
required. Keep project dependencies on the container volumes rather than installing
`backend/.venv` or `frontend/node_modules` on the host.

In VS Code, use **Dev Containers: Reopen in Container**. A headless setup also
requires Node.js for the devcontainer CLI:

```console
npx @devcontainers/cli up --workspace-folder .
npx @devcontainers/cli exec --workspace-folder . just check
```

Inside the devcontainer, the common commands are:

```console
just dev-backend  # FastAPI development server
just dev-frontend # Vite development server
just types        # regenerate frontend API types after schema changes
just check        # full required quality gate
```

## Change workflow

New features, behavior changes, and architecture decisions require an OpenSpec change
under `openspec/changes/` before implementation. Contributors can prepare the OpenSpec
artifacts and implementation without prior maintainer approval; the maintainer
reviews both in the pull request. Bug fixes that restore specified behavior,
documentation, chores, and dependency updates do not require an OpenSpec change.

Use a focused branch:

- `change/<openspec-change-id>` for OpenSpec changes
- `fix/<slug>` for bug fixes
- `chore/<slug>` for documentation, maintenance, and dependency updates

Use Conventional Commit subjects (`feat:`, `fix:`, `docs:`, `test:`, `refactor:`, or
`chore:`), written imperatively and no longer than 72 characters.

## Implementation expectations

- Prefer the smallest maintainable solution; new dependencies need clear
  justification.
- Preserve the boundaries and security invariants in
  [the architecture guide](docs/ARCHITECTURE.md) and
  [the security checklist](docs/SECURITY.md).
- Keep backend and frontend types aligned. Frontend API types are generated from the
  backend OpenAPI schema rather than maintained separately.
- Add or update tests for changed behavior.

## Versioning

Tasterr uses SemVer (`MAJOR.MINOR.PATCH`) for its supported operator contracts:
configuration/environment variables, the image and its tags, the health endpoint,
persisted data and upgrade/downgrade paths, and documented operator procedures.

The SPA-internal `/api/v1` backend is private. It is versioned with the bundled
frontend, shipped in the same image, and not covered by SemVer as a supported
integration surface. The health endpoint remains a supported operator contract.

- **MAJOR:** breaking supported operator contracts, or a required manual migration
  step.
- **MINOR:** backward-compatible features or opt-in/opt-out behavior changes.
- **PATCH:** fixes only.

Automatic startup migrations can accompany a feature release; a destructive
downgrade still needs an explicit warning. The historical [release
records](docs/releases/) include feature releases such as `2.2.0` and `2.3.0`
and the sign-in fix in `2.3.1`.

Accumulate user-facing changes and upgrade warnings under
[`docs/releases/`](docs/releases/) between releases, creating `unreleased.md`
when the next changes arrive.
During release readiness, choose the version, rename that file to `vX.Y.Z.md`,
and complete its verification evidence. Synchronize package versions, image pins,
and release references together using the [release procedure](docs/RELEASING.md).
Documentation refreshes do not assign a new release version.

## Documentation screenshots

Run `just screenshots` inside the devcontainer to rebuild the SPA and replace
the five JPEGs in `docs/screenshots/`: Home, detail, search, Account, and household
picks. Captures use the default dark theme at 1440×900; Account uses a full-page
capture from the top so all five taste-source controls are visible together.
Install Chromium first using the command under Pull requests if needed. The opt-in
Playwright configuration uses `backend/scripts/e2e_server.py`, disposable state,
invented catalog data, and locally generated artwork; it refuses external browser
requests. It is excluded from `just check` and ordinary `just e2e` runs. Open all
five images and review them for private data before staging.

## Pull requests

Before opening a pull request:

1. Run `just check` inside the devcontainer.
2. Archive a completed OpenSpec change on its branch, when applicable.
3. Review the full diff for secrets, credentials, private URLs, household data, and
   unrelated changes.
4. Complete the pull request template. Use the Conventional Commit subject as the
   pull request title.

The required PR checks are `check`, `e2e`, `container-smoke`, and GitHub's `CodeQL`
analysis. To reproduce the three repository-owned checks locally, install Chromium
once inside the devcontainer and run:

```console
cd frontend && npx playwright install --with-deps chromium
cd ..
just release-check
```

Pull requests are squash-merged after those checks pass.

By contributing, you agree that your contribution is licensed under the repository's
[AGPL-3.0-only license](LICENSE).

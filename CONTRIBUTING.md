# Contributing to Tasterr

Thanks for helping improve Tasterr. Small, focused changes are the easiest to review
and maintain. Participation is governed by the [Code of Conduct](CODE_OF_CONDUCT.md).

## Before you start

- Search existing issues before opening a new one.
- Use the [issue chooser](https://github.com/ZacharyArthur/tasterr/issues/new/choose)
  for bug reports and feature requests.
- Report vulnerabilities privately as described in [SECURITY.md](SECURITY.md).
- Open a feature request before investing in a substantial change so its scope can
  be agreed first.

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
under `openspec/changes/` before implementation. Start with a feature request; after
its scope is agreed, the maintainer will coordinate the OpenSpec artifacts. Bug fixes
that restore specified behavior, documentation, chores, and dependency updates do
not require an OpenSpec change.

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

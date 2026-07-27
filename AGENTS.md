# Tasterr

Self-hosted, Netflix-style discovery front-end for a household media stack (TMDB
catalog + Seerr identity/requests) with **per-user learned taste profiles**.
Solo-maintained. Optimizes for, in order: **best practice, KISS, maintainable code**.
When a feature and simplicity conflict, simplicity wins or the feature waits.

## Stack

- Backend: Python 3.13, FastAPI, Pydantic v2, SQLAlchemy 2.0 + Alembic on SQLite,
  httpx. Tooling: uv, ruff, pyright (strict), pytest.
- Frontend: Vite + React + TypeScript (strict) + Tailwind + TanStack Query.
  Tooling: Biome, Vitest. CSS-first animation.
- One process, one Docker image, in-process cache, asyncio background work.
  No Redis, no celery. New dependencies need explicit justification.

## Layout & hard invariants

```
backend/src/tasterr/   api/ auth/ clients/ catalog/ rails/ recommend/ db/
frontend/src/          routes/ components/ lib/
openspec/              living specs + change proposals (source of truth)
docs/                  founding blueprint (PRD, SPEC - frozen), SECURITY.md (living), spikes
```

Invariants (enforced by boundary tests + PublicConfig regression test, not prose):

1. **Secrets never reach the client** — TMDB/Seerr keys, Seerr internal URL, Plex
   tokens, Seerr cookies are server-side only. Client gets `PublicConfig` only.
2. **Only `clients/` does outbound HTTP**; only `api/` shapes browser responses.
3. **Seerr down degrades** (badges "Unknown", requests disabled) — never blocks browsing.

## Development environment — devcontainer REQUIRED

**All development happens inside the devcontainer (`.devcontainer/`). No exceptions.**
Do not install, repair, or run the toolchain (uv, Python, node/npm, just) on the
Windows host — the host toolchain is deliberately absent and unmaintained (host
antivirus has quarantined toolchain binaries and project sources mid-session;
see m0-scaffold design.md, decision 12). If a command needs uv/npm/just, it runs
in the container, full stop.

- The repo stays in the local folder, bind-mounted at `/workspaces/tasterr` —
  edits and git history are the same files on the host.
- `backend/.venv` and `frontend/node_modules` live on named container volumes and
  must never materialize on the host filesystem.
- VS Code: "Reopen in Container". Headless / agents:
  `npx @devcontainers/cli up --workspace-folder .` once, then
  `npx @devcontainers/cli exec --workspace-folder . <command>` for everything else.
- `docker build` / `docker run` work inside the container via
  docker-outside-of-docker (they drive the host engine).

## Quality gate

```
just check     # ruff + pyright + pytest + frontend typecheck/test/build
```

Run it **inside the devcontainer** (see above); CI runs the exact same command on
PRs. Never claim work is done until it passes.

## Development workflow (OpenSpec)

- **New features, behavior changes, and architecture decisions** go through an
  OpenSpec change first. Bug fixes restoring already-specified behavior, docs,
  chores, and dep bumps go straight to a branch.
- `openspec/specs/` is the **living source of truth** for current behavior.
  `docs/PRD.md` and `docs/SPEC.md` are the frozen founding blueprint —
  consult them for rationale, never update them.

Starting work on something, in order:

1. `/opsx:explore` — optional: think the problem through before committing to a change.
2. `/opsx:propose <kebab-name>` — creates `openspec/changes/<id>/` with
   `proposal.md` (what/why), `design.md` (how), `tasks.md` (steps).
   `openspec/config.yaml` injects project context and required sections —
   notably, every design.md must address **Security considerations**
   (see docs/SECURITY.md).
3. Branch: `git switch -c change/<id>`.
4. `/opsx:apply` — implement `tasks.md` top to bottom, checking tasks off as they
   land. `just check` must pass before any task is called done.
5. `/opsx:archive` — **on the branch, before merging** — archives the change and
   updates `openspec/specs/`, so code + spec land atomically in one squash.
6. Open the PR per the Git workflow below.

No slash commands available? Drive the same flow with the CLI:
`openspec new change "<name>"`, `openspec status --change <id> --json`,
`openspec instructions <artifact> --change <id> --json`, `openspec validate`,
`openspec archive <id>`.

## Security

Security is a design input, not a review step. The invariants above are the
non-negotiables; **[docs/SECURITY.md](docs/SECURITY.md)** holds the threat model
and per-area checklists (endpoints, auth/sessions, outbound HTTP, frontend, DB,
dependencies). Walk the relevant checklist whenever touching `api/`, `auth/`,
`clients/`, or `db/`, and answer it in the change's design.md.

## Git workflow

- `main` is always releasable. Every change lands through a pull request. Branch per
  change: `change/<openspec-change-id>`; `fix/<slug>` / `chore/<slug>` for non-spec
  work. Trivial fixes (typos, docs, dep bumps) may skip OpenSpec, not the branch/PR.
- **Conventional Commits**: `feat:` `fix:` `refactor:` `docs:` `test:` `chore:`,
  imperative subject <= 72 chars.
- PRs: **squash merge**, self-approved. PR title = the Conventional Commit subject
  (it becomes the commit on `main`). Body follows `.github/pull_request_template.md`
  (what/why, OpenSpec change id or `n/a`, gate-passes checkbox).
- **Never mention AI tools/assistants** — or this file, CLAUDE.md, or the agent
  workflow — in ANY committed artifact: commit messages, PR titles/bodies, issues,
  code comments, docstrings, docs. Sole exceptions: AGENTS.md, CLAUDE.md, `openspec/`.
- AI tool dot-folders (`.claude/`, `.cursor/`, etc.) are gitignored; AGENTS.md,
  CLAUDE.md, and `openspec/` are committed.
- Always show the exact commit message / PR text and get explicit confirmation
  before running `git commit`, `git push`, or `gh pr create`.

## Code conventions

- Boring, obvious code beats clever code. Small modules, pure domain logic between
  `api/` and `clients/` that unit-tests without network mocks.
- Typed end-to-end: no `Any`/`any` escapes without a stated reason. Frontend API
  types are generated from the backend OpenAPI schema — never hand-written twice.
- Tests accompany behavior, especially: recommendation math, auth/session lifecycle,
  boundary contracts, config scrubbing.
- Match surrounding style; comments only for constraints the code can't express.

## Reference

[janpuc/browserr](https://github.com/janpuc/browserr) — the Next.js predecessor this
project is a clean rebuild of — may be consulted for UX patterns, API shapes, and
client resilience patterns. **Consult, don't port.**

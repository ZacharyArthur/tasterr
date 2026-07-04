# Design: m0-scaffold

## Context

The repo is docs-only (PRD, SPEC, SECURITY, spike findings). M0 turns SPEC §2/§3
into a running skeleton: the locked stack installed, boundary invariants enforced
mechanically from the first commit, one gate command, and a container that serves a
hello-world SPA. Everything here is greenfield; the only constraints are the frozen
blueprint and the AGENTS.md stack slate.

## Goals / Non-Goals

**Goals:**

- Repo layout exactly per SPEC §3, with real (importable, boundary-tested) packages
  even where they are still empty.
- `just check` as the single gate, identical locally, in CI, and for agents.
- Settings + PublicConfig with the no-secrets regression test in place before any
  secret exists to leak.
- DB engine + Alembic migrate-on-boot proven end to end with a baseline migration.
- Docker image (non-root, healthcheck) and compose example that serve the SPA.

**Non-Goals:**

- Any feature behavior: no auth, no outbound HTTP, no domain tables, no rails.
  `clients/`, `auth/`, `catalog/`, `rails/`, `recommend/` are laid out but empty.
- Image-publish workflow, rate limiting, Playwright (M6); settings GUI (M5).

## Decisions

1. **Backend is a uv project at `backend/` with a src layout** (`backend/src/tasterr`),
   tests in `backend/tests`. Alternative — root-level pyproject — rejected: keeps the
   frontend/backend split symmetrical and matches SPEC §3 verbatim.

2. **Integration secrets are optional at boot.** `TMDB_API_KEY`, `SEERR_*`, and
   `TASTERR_SECRET_KEY` are `SecretStr | None`; `/api/v1/health` reports per-integration
   configured booleans. Rationale: SPEC's degradation philosophy (Seerr down never
   blocks browsing) applies to "not configured yet" too, and tests/CI must run with
   no real env. Alternative — required-at-boot fail-fast — rejected: would crash the
   container before an admin can even see health. `DATABASE_PATH` defaults to
   `./data/tasterr.db` (container overrides to `/data/tasterr.db`).

3. **PublicConfig is an allowlist projection** (explicit field-by-field constructor
   from `Settings`, the browserr `toPublicConfig` pattern), never a field-exclusion
   of the settings model. The regression test does two things: asserts no
   denylisted field name (`*key*`, `*secret*`, `*token*`, `*internal*`) appears in
   the model schema, and serializes a projection built from settings populated with
   sentinel values, asserting no sentinel appears in the output. In M0 PublicConfig
   is model + test only; the session-gated `/config` endpoint arrives with M1 auth.

4. **Alembic runs at startup via the documented async pattern** (`connection.run_sync`
   against the async engine inside lifespan). The baseline migration is an empty
   revision: it proves create/upgrade/no-op-reboot without speculatively freezing
   schema — tables land with the features that need them (M1+). Alternative —
   creating the §5 tables now — rejected: schema decisions belong to the milestones
   that test them.

5. **SPA serving**: mount built assets, plus a catch-all that returns `index.html`
   for non-`/api` paths; `/api/v1/*` unknowns stay JSON 404 (registered routes take
   precedence; the catch-all explicitly excludes `/api`). In dev, the Vite server
   proxies `/api` to uvicorn — same-origin in both modes, so no CORS middleware
   exists at all.

6. **OpenAPI typegen is dev-time and committed**: a `just types` recipe dumps
   `app.openapi()` to JSON and runs `openapi-typescript` into
   `frontend/src/lib/api.gen.ts`; a thin hand-written `fetch` wrapper types against
   it. Alternative — `openapi-fetch` runtime client — rejected: adds a runtime
   dependency for one endpoint; revisit if the wrapper grows hairy. Alternative —
   generating during build — rejected: build would then need a live backend; a
   committed file keeps `just check` hermetic.

7. **Boundary enforcement via import-linter** (SPEC §11) with two contracts:
   `httpx` importable only by `tasterr.clients.*`, and `tasterr.api` not importable
   from other `tasterr` packages. Scope is the `tasterr` package — tests may use
   httpx's `ASGITransport` as the test client freely.

8. **justfile recipes are plain cross-platform invocations** (`uv run ruff check …`,
   `npm --prefix frontend run …`) so the same file works on the Windows dev machine
   and Linux CI/container without shell-specific syntax.

9. **CI**: one workflow, ubuntu-latest, installs uv + node + just, runs `just check`.
   Nothing else — the command is the contract.

10. **Dockerfile**: `node:22-slim` builds `frontend/dist` → `python:3.13-slim` with
    the uv binary copied from the official distroless image, `uv sync --frozen
    --no-dev`, non-root `app` user, `HEALTHCHECK` via a stdlib `urllib` one-liner
    (no curl in slim), SQLite on a `/data` volume. amd64 + arm64 both work (all
    bases are multi-arch); publish workflow is M6.

11. **"Gate passes in container" (M0 done-when)** is read as: `just check` green in
    CI **and** the built image runs, passes its healthcheck, and serves the SPA.
    Running dev tooling inside the runtime image was rejected — the production
    image must not contain dev dependencies.

12. **Devcontainer as the primary dev environment** (added mid-change). The host
    antivirus (Bitdefender) quarantined toolchain binaries (`uv.exe`, `just.exe`,
    venv entry points) and project sources mid-implementation, and blocks package
    downloads at the firewall. `.devcontainer/` bind-mounts the repo from the
    local folder (source of truth stays on the host) while the toolchain and both
    dependency trees live in the container: `backend/.venv` and
    `frontend/node_modules` are named volumes — faster than Windows bind mounts
    and invisible to host AV. `docker build` works inside via the
    docker-outside-of-docker feature (host engine). Alternative — WSL2-native
    checkout — rejected: the repo must stay in the local Windows folder per the
    owner's workflow. The host toolchain still works where available; CI is
    unaffected either way.

**New dependencies vs. the AGENTS.md slate** (everything else is the slate itself):

| Dependency | Kind | Justification |
|---|---|---|
| uvicorn | backend runtime | The ASGI server FastAPI requires; implied by the slate |
| aiosqlite | backend runtime | The async SQLite driver SQLAlchemy async mode requires |
| alembic | backend runtime | Named in the slate (SQLAlchemy 2.0 + Alembic) |
| import-linter | backend dev | Named in SPEC §11 as the boundary-test mechanism |
| pip-audit | backend dev | Named in SPEC §9 (`just audit`) |
| openapi-typescript | frontend dev | Implements the "types generated from OpenAPI, never hand-written twice" rule |

Note: frontend TypeScript is pinned to ~5.9 (not the 6.x the Vite template ships)
because openapi-typescript peers on `^5.x`; the typegen invariant outranks having
the newest compiler. Revisit when openapi-typescript supports TS 6.

Note: @biomejs/biome is pinned exactly to 2.4.2 — the 2.5.x win32-arm64 CLI binary
crashes (access violation) on the ARM64 dev machine; 2.4.2 is the newest release
whose binary works. Revisit on the next Biome release.

## Security considerations

Per docs/SECURITY.md, walked for the areas this change touches:

- **New endpoint (`/api/v1/health`)**: unauthenticated by explicit decision —
  liveness must work before login exists (M1) and the container healthcheck depends
  on it. It takes no input, mutates nothing (GET-only ⇒ no CSRF surface), has an
  explicit `response_model` returning only a status string and configured booleans —
  no versions, URLs, stack traces, or upstream bodies. Rate limiting is deferred to
  M6 with the rest of the rate-limit work; acceptable because the response is
  static, cheap, and secret-free.
- **Auth & session checklist**: N/A — no auth code exists in M0.
- **Outbound HTTP checklist**: N/A by construction — `clients/` is empty and the
  import-linter contract prevents httpx use anywhere else, so the checklist cannot
  be bypassed silently.
- **Frontend**: hello-world page renders only typed API data as text; no
  `dangerouslySetInnerHTML`, nothing stored in localStorage/sessionStorage.
- **Database & migrations**: SQLAlchemy expressions only (nothing string-built);
  the baseline migration creates no columns, secret or otherwise.
- **Dependencies & build**: additions justified above; `uv.lock` and
  `package-lock.json` committed with this change; Dockerfile uses a minimal base,
  non-root user, no secrets in layers or build args; `.env.example` is
  placeholder-only (release-checklist item enforced from day one).
- **Secrets-never-reach-the-client invariant**: the PublicConfig regression test
  lands in this change, before any secret-bearing endpoint exists.
- **Devcontainer**: runs as the non-root `vscode` user; docker-outside-of-docker
  grants the container control of the host Docker engine — acceptable for a
  single-developer machine (the devcontainer runs only this repo's tooling), and
  no secrets are baked into the dev image (env stays in the untracked `.env`).

## Risks / Trade-offs

- [justfile drifts between Windows dev and Linux CI] → recipes restricted to plain
  tool invocations; CI runs the identical command and is the arbiter.
- [Committed generated types (`api.gen.ts`) go stale vs. the OpenAPI schema] →
  regenerating is one `just types` away and the frontend typecheck catches breaking
  drift at the call site; an automated staleness check is deliberately deferred (KISS).
- [Empty baseline migration feels like ceremony] → it is the cheapest proof that
  migrate-on-boot, double-boot idempotency, and the Alembic wiring work before M1
  depends on them.
- [Catch-all SPA route could shadow API 404 behavior] → explicit test asserting
  unknown `/api/v1/*` returns JSON 404, not `index.html`.
- [Optional secrets could let a misconfigured deploy run silently] → health exposes
  configured flags, and M1+ features that need a secret will fail loudly at their
  own boundary.
- [Host antivirus quarantines toolchain/source files mid-work] → devcontainer keeps
  tooling and dependency trees off the host filesystem; the repo folder is
  AV-excepted; committed work is recoverable from git objects.

## Migration Plan

Greenfield — nothing to migrate. Rollback is `git revert`; no data or deploys exist.

## Open Questions

None — the frozen SPEC answers the scope questions, and the auth spike already
de-risked the sequencing (M0 → M1).

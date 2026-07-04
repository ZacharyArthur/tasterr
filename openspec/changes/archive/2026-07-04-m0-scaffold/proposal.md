# Proposal: m0-scaffold

## Why

The repo currently contains only founding docs — no code, no tooling, no gate. Every
later milestone (auth, browse, taste engine) assumes a working skeleton: the locked
stack installed and configured, the boundary invariants mechanically enforced from
day one, and a single `just check` gate that humans, agents, and CI all run
identically. M0 builds that skeleton so M1+ changes are pure feature work.

This advances **PRD/SPEC milestone M0 (Scaffold)** — SPEC §13: "Repo layout, tooling,
settings, DB+Alembic, Docker skeleton, hello-world SPA served by FastAPI. Done when:
gate passes in container."

## What Changes

- **Repo layout** per SPEC §3: `backend/src/tasterr/` (with empty-but-real `api/`,
  `auth/`, `clients/`, `catalog/`, `rails/`, `recommend/`, `db/` packages),
  `backend/tests/`, `frontend/src/` (`routes/`, `components/`, `lib/`), root
  `justfile`, `Dockerfile`, `docker-compose.yml`, `.env.example`.
- **Backend tooling**: uv project (Python 3.13), ruff (lint + format), pyright
  strict, pytest + pytest-asyncio; `uv.lock` committed.
- **Frontend tooling**: Vite + React + TypeScript strict + Tailwind + TanStack
  Query; Biome (lint + format), Vitest; `package-lock.json` committed.
- **Settings**: pydantic-settings model with env-only secrets (`TMDB_API_KEY`,
  `SEERR_INTERNAL_URL`, `SEERR_EXTERNAL_URL`, `SEERR_API_KEY`, `TASTERR_SECRET_KEY`,
  `DATABASE_PATH`, bind host/port) and a `PublicConfig` projection with a
  no-secrets regression test.
- **DB + Alembic**: async SQLAlchemy 2.0 engine on SQLite, Alembic wired with a
  baseline migration, idempotent migrate-on-boot in the app lifespan.
- **App shell**: FastAPI app factory serving `/api/v1/health` plus the built SPA
  (static assets + index fallback). Hello-world SPA calls `/api/v1/health` through
  an API client typed from the generated OpenAPI schema.
- **Boundary enforcement**: import-linter contracts (only `clients/` may import
  httpx; the layering between `api/` and `clients/`) wired into the gate.
- **Quality gate**: `just check` = ruff + pyright + pytest + Biome + tsc + Vitest
  + frontend build; `just audit` = pip-audit + npm audit (advisory). GitHub Actions
  gate workflow runs `just check` on every PR.
- **Container**: multi-stage Dockerfile (node builds SPA → python 3.13-slim runtime,
  non-root user, healthcheck), docker-compose example beside Seerr, `.env.example`
  with placeholders only.
- **Devcontainer**: `.devcontainer/` provides the full toolchain (uv, node, just)
  in a Linux container with the repo bind-mounted from the local folder, so
  `just check` runs identically without installing dev dependencies on the host
  (added mid-change: host antivirus quarantined toolchain binaries and sources).

## Capabilities

### New Capabilities

- `dev-tooling`: repo layout, the `just check` quality gate, boundary enforcement
  (import-linter), OpenAPI→TypeScript type generation, the CI gate workflow, and
  the devcontainer dev environment.
- `app-settings`: env-driven settings model, env-only secrets, and the
  `PublicConfig` no-secrets projection.
- `app-database`: async SQLAlchemy engine on SQLite and Alembic migrations applied
  idempotently on boot.
- `app-shell`: FastAPI app factory and lifespan, the `/api/v1/health` endpoint, and
  SPA serving (static assets + index fallback) with the hello-world frontend.
- `container-deploy`: Docker image, compose example, and `.env.example` contract.

### Modified Capabilities

_None — this is the first change; no living specs exist yet._

## Non-goals

- No authentication, sessions, or admin gate (M1) — `/api/v1/health` is the only
  endpoint, deliberately unauthenticated (liveness must work pre-login).
- No TMDB/Seerr/Plex clients or outbound HTTP at all (M2/M3) — `clients/` stays empty.
- No domain tables; the Alembic baseline proves the pipeline, schema arrives with
  the features that need it (M1+).
- No `/config` endpoint — `PublicConfig` lands as a tested projection only; the
  session-gated endpoint arrives with auth (M1).
- No image-build/GHCR workflow (M6), no Playwright e2e (M6), no rate limiting (M6),
  no settings GUI (M5).

## Impact

- **Code**: everything is new; no existing code affected. Establishes the module
  boundaries all later milestones build on.
- **Dependencies**: the locked stack from SPEC §2 plus dev-only additions justified
  in design.md (import-linter, openapi-typescript, pip-audit).
- **CI**: new gate workflow; PRs are blocked on `just check` from this change onward.
- **Docs**: none — PRD/SPEC stay frozen; `openspec/specs/` gains its first five
  living capability specs when this change archives.

# Tasks: m0-scaffold

## 1. Backend project skeleton

- [x] 1.1 Create the uv project at `backend/` (Python 3.13, src layout): `pyproject.toml`
      with fastapi, uvicorn, pydantic-settings, sqlalchemy, aiosqlite, alembic, httpx;
      dev group with ruff, pyright, pytest, pytest-asyncio, import-linter, pip-audit.
      Commit `uv.lock`.
- [x] 1.2 Configure tooling in `pyproject.toml`: ruff (lint + format), pyright strict,
      pytest + pytest-asyncio settings.
- [x] 1.3 Create the `tasterr` package layout per SPEC §3: `main.py`, `settings.py`,
      and `api/ auth/ clients/ catalog/ rails/ recommend/ db/` packages (empty
      `__init__.py` where no content yet), plus `backend/tests/` mirroring src.
- [x] 1.4 Add import-linter contracts (httpx only importable by `tasterr.clients`;
      `tasterr.api` not importable from other `tasterr` packages) and verify
      `lint-imports` passes against the skeleton.

## 2. Settings & PublicConfig

- [x] 2.1 Implement `settings.py`: pydantic-settings model with optional `SecretStr`
      integration secrets (`TMDB_API_KEY`, `SEERR_INTERNAL_URL`, `SEERR_EXTERNAL_URL`,
      `SEERR_API_KEY`, `TASTERR_SECRET_KEY`), `DATABASE_PATH` (default
      `./data/tasterr.db`), bind host/port — with tests covering env population and
      boot-with-nothing-set.
- [x] 2.2 Implement the `PublicConfig` allowlist projection and its no-secrets
      regression test (denylisted names absent from schema; sentinel secret values
      absent from serialized output).

## 3. Database & migrations

- [x] 3.1 Implement `db/engine.py`: async SQLAlchemy engine bound to `DATABASE_PATH`,
      with a test that the file is created on first connect.
- [x] 3.2 Wire Alembic under `db/alembic/` with the empty baseline revision and a
      programmatic `upgrade head` helper, with tests: fresh DB migrates to head,
      second run is a no-op.

## 4. App shell (API + SPA serving)

- [x] 4.1 Implement the app factory and lifespan in `main.py` (migrate on startup),
      with a test that the factory returns a working app and startup runs migrations.
- [x] 4.2 Implement `GET /api/v1/health` in `api/` with an explicit response model
      (status + per-integration configured flags), with tests: 200 shape, flags flip
      with settings, no secret material in the body.
- [x] 4.3 Implement SPA static serving + index fallback, with tests: non-API path
      returns `index.html`; unknown `/api/v1/*` returns JSON 404.

## 5. Frontend skeleton

- [x] 5.1 Scaffold `frontend/` with Vite + React + TypeScript strict + Tailwind +
      TanStack Query; Biome and Vitest configured; `routes/ components/ lib/` dirs;
      Vite dev proxy for `/api`. Commit `package-lock.json`.
- [x] 5.2 Add the `just types` OpenAPI→TypeScript generation (dump `app.openapi()`,
      run openapi-typescript into `src/lib/api.gen.ts`, committed) and the thin typed
      fetch wrapper in `lib/`.
- [x] 5.3 Build the hello-world route: fetch `/api/v1/health` via the typed wrapper +
      TanStack Query and render the status, with a Vitest test of the rendering.

## 6. Gate & CI

- [x] 6.1 Write the root `justfile`: `check` (ruff, pyright, lint-imports, pytest,
      Biome, tsc, Vitest, frontend build), `types`, `audit` (pip-audit + npm audit,
      advisory), `dev` helpers — plain cross-platform invocations only.
- [x] 6.2 Add the GitHub Actions gate workflow running `just check` on every PR.

## 7. Container

- [x] 7.1 Write the multi-stage `Dockerfile` (node builds SPA → python:3.13-slim +
      uv runtime, `--frozen --no-dev`, non-root user, stdlib healthcheck, `/data`
      volume) and `.dockerignore`.
- [x] 7.2 Write `docker-compose.yml` (Tasterr beside Seerr on a shared network,
      SQLite named volume) and `.env.example` listing every env var with
      placeholders only.
- [x] 7.3 Build and run the image locally: healthcheck goes healthy, `/api/v1/health`
      returns 200, SPA loads at `/`, process runs as non-root (M0 done-when proof).
- [x] 7.4 Write `.devcontainer/` (Dockerfile + devcontainer.json): uv/node/just in
      the container, repo bind-mounted, `.venv` and `node_modules` on named volumes,
      docker-outside-of-docker for image builds.
- [x] 7.5 Verify `just check` passes inside the devcontainer (same command, no
      host toolchain).

## 8. Gate

- [x] 8.1 Run `just check` and fix any failures until it passes clean.

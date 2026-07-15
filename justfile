# cmd.exe understands `cd x && cmd` like sh does; recipes stay cross-platform.
set windows-shell := ["cmd.exe", "/c"]

# Full quality gate — identical for humans, agents, and CI.
check: check-backend check-types-fresh check-frontend

check-backend:
    cd backend && uv run ruff check .
    cd backend && uv run ruff format --check .
    cd backend && uv run pyright
    cd backend && uv run lint-imports
    cd backend && uv run pytest -q

check-frontend:
    cd frontend && npm run lint
    cd frontend && npm run typecheck
    cd frontend && npm test
    cd frontend && npm run build

# Hermetic browser journey: compiled SPA + normal FastAPI app + local upstream fixtures.
e2e:
    cd frontend && npm run build
    cd frontend && npm run e2e

# Native production-image and named-volume contract; owns all disposable resources.
container-smoke:
    bash scripts/container-smoke.sh

# Deterministic pre-release checks. Audits and live contracts stay explicit.
release-check:
    just check
    just e2e
    just container-smoke

# Regenerate frontend API types from the backend OpenAPI schema.
types:
    cd backend && uv run python scripts/dump_openapi.py ../frontend/openapi.json
    cd frontend && npx openapi-typescript openapi.json -o src/lib/api.gen.ts

# Fail the gate if the committed generated API types have drifted from the schema.
# Regenerates to a scratch file and diffs — no git, so it works the same in the
# devcontainer (bind-mounted repo) and in CI.
check-types-fresh:
    cd backend && uv run python scripts/dump_openapi.py ../frontend/openapi.json
    cd frontend && npx openapi-typescript openapi.json -o src/lib/api.gen.ts.check
    cd frontend && { diff -u src/lib/api.gen.ts src/lib/api.gen.ts.check; rc=$?; rm -f src/lib/api.gen.ts.check; exit $rc; }

# Live Seerr contract tests (excluded from `check`): set TASTERR_LIVE_SEERR_URL,
# TASTERR_LIVE_SEERR_EMAIL, TASTERR_LIVE_SEERR_PASSWORD (and optionally
# TASTERR_LIVE_PLEX_TOKEN for the /auth/plex path) in the environment first.
test-live:
    cd backend && uv run pytest -m live -s

# Dependency audit — advisory, not part of `check`. The `-` keeps a backend
# advisory from hiding the frontend report.
audit:
    -cd backend && uv run pip-audit
    cd frontend && npm audit

dev-backend:
    cd backend && uv run uvicorn tasterr.main:create_app --factory --reload

dev-frontend:
    cd frontend && npm run dev

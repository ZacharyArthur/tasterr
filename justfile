# cmd.exe understands `cd x && cmd` like sh does; recipes stay cross-platform.
set windows-shell := ["cmd.exe", "/c"]

# Full quality gate — identical for humans, agents, and CI.
check: check-backend check-frontend

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

# Regenerate frontend API types from the backend OpenAPI schema.
types:
    cd backend && uv run python scripts/dump_openapi.py ../frontend/openapi.json
    cd frontend && npx openapi-typescript openapi.json -o src/lib/api.gen.ts

# Live Seerr contract tests (excluded from `check`): set TASTERR_LIVE_SEERR_URL,
# TASTERR_LIVE_SEERR_EMAIL, TASTERR_LIVE_SEERR_PASSWORD in the environment first.
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

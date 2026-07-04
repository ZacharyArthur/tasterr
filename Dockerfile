# Stage 1: build the SPA
FROM node:24-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: python runtime serves the API and the built SPA
FROM python:3.13-slim
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    STATIC_DIR=/app/static \
    DATABASE_PATH=/data/tasterr.db \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

# Dependency layer first so code changes don't re-resolve the environment.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY backend/src ./src
RUN uv sync --frozen --no-dev

COPY --from=frontend /build/dist ./static

RUN groupadd --system app && useradd --system --gid app app \
    && mkdir /data && chown app:app /data
USER app

VOLUME /data
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD ["python", "-c", "import os, sys, urllib.request; port = os.environ.get('TASTERR_PORT', '8000'); sys.exit(0 if urllib.request.urlopen(f'http://127.0.0.1:{port}/api/v1/health', timeout=3).status == 200 else 1)"]

CMD ["python", "-m", "tasterr"]

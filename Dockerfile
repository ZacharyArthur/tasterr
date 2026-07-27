# Keep uv on a FROM line so Dependabot can update its digest.
FROM ghcr.io/astral-sh/uv:0.11@sha256:df4cae8f3a96d175e2e5f992e597550000edbe78fdc2594d5cd8de1a217f504c AS uv

# Build the SPA.
FROM node:26-slim@sha256:715e55e4b84e4bb0ff48e49b398a848f08e55daed8eb6a0ea1839ae53bc57583 AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Serve the API and built SPA from the Python runtime.
FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
COPY --from=uv /uv /uvx /usr/local/bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    STATIC_DIR=/app/static \
    DATABASE_PATH=/data/tasterr.db \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app

COPY LICENSE /usr/share/licenses/tasterr/LICENSE

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

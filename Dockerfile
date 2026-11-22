# Keep uv on a FROM line so Dependabot can update its digest.
FROM ghcr.io/astral-sh/uv:0.13@sha256:d3b601f0c7b118bc1753febf7c41cc80981df678445e0254284eecf84db79a7d AS uv

# Build the SPA.
FROM node:26-slim@sha256:e6bedef217677b276c591795e169840edd9096dbf13f29df8ef8d1856b8820bc AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Serve the API and built SPA from the Python runtime.
FROM python:3.15-slim@sha256:65a65fc7b30b06cb6df4930fd4650697cb23f4c2698ab81fc87e4b031bc36928
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

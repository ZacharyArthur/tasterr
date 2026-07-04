"""App factory and lifespan: migrate on boot, serve the API and the SPA."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.types import ASGIApp, Receive, Scope, Send

from tasterr.api.meta import router as meta_router
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(started_app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(app_settings.database_path)
        started_app.state.engine = engine
        try:
            await upgrade_to_head(engine)
            yield
        finally:
            await engine.dispose()

    # OpenAPI/docs are not served: the schema is dumped offline for typegen
    # (`just types`), and no browser needs it (default-deny).
    app = FastAPI(
        title="Tasterr",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.dependency_overrides[get_settings] = lambda: app_settings

    app.include_router(meta_router, prefix="/api/v1")
    app.add_middleware(SpaFallback, static_dir=app_settings.static_dir)
    return app


class SpaFallback:
    """Serve the built SPA for non-API paths, at the ASGI level.

    /api/* traffic passes through untouched so the router fully owns its
    method semantics (404 for unknown paths, 405 with Allow for known paths,
    for every HTTP verb). Everything else: GET/HEAD serve a real file or fall
    back to index.html; other methods are 405.
    """

    def __init__(self, app: ASGIApp, static_dir: Path) -> None:
        self.app = app
        self.static_root = static_dir.resolve()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or self._is_api(scope["path"]):
            await self.app(scope, receive, send)
            return
        response = self._spa_response(scope["path"], scope["method"])
        await response(scope, receive, send)

    @staticmethod
    def _is_api(path: str) -> bool:
        return path == "/api" or path.startswith("/api/")

    def _spa_response(self, path: str, method: str) -> Response:
        if method not in ("GET", "HEAD"):
            return JSONResponse(
                {"detail": "Method Not Allowed"},
                status_code=405,
                headers={"Allow": "GET, HEAD"},
            )
        candidate = (self.static_root / path.lstrip("/")).resolve()
        if candidate.is_file() and candidate.is_relative_to(self.static_root):
            return FileResponse(candidate)
        index_file = self.static_root / "index.html"
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse({"detail": "SPA assets not built"}, status_code=404)

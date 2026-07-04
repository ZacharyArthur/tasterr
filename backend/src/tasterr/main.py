"""App factory and lifespan: migrate on boot, serve the API and the SPA."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response

from tasterr.api.meta import router as meta_router
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(app_settings.database_path)
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
    _mount_spa(app, app_settings.static_dir)
    return app


def _mount_spa(app: FastAPI, static_dir: Path) -> None:
    """Serve built SPA assets; any unknown non-API path falls back to index.html."""
    static_root = static_dir.resolve()
    index_file = static_root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def spa(full_path: str) -> Response:  # pyright: ignore[reportUnusedFunction]
        if full_path == "api" or full_path.startswith("api/"):
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        candidate = (static_root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(static_root):
            return FileResponse(candidate)
        if index_file.is_file():
            return FileResponse(index_file)
        return JSONResponse({"detail": "SPA assets not built"}, status_code=404)

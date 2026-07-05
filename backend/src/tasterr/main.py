"""App factory and lifespan: migrate on boot, serve the API and the SPA."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tasterr.api.auth import router as auth_router
from tasterr.api.meta import router as meta_router
from tasterr.auth.cookies import COOKIE_NAME, session_cookie_header
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import sweep_expired
from tasterr.clients.http import create_http_client
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings if settings is not None else get_settings()

    @asynccontextmanager
    async def lifespan(started_app: FastAPI) -> AsyncGenerator[None]:
        engine = create_engine(app_settings.database_path)
        started_app.state.engine = engine
        http = create_http_client()
        started_app.state.http = http
        try:
            await upgrade_to_head(engine)
            sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
            started_app.state.sessionmaker = sessionmaker
            async with sessionmaker() as db:
                await sweep_expired(db)
            yield
        finally:
            await http.aclose()
            await engine.dispose()

    # OpenAPI/docs are not served: the schema is dumped offline for typegen
    # (`just types`), and no browser needs it (default-deny).
    app = Tasterr(
        title="Tasterr",
        lifespan=lifespan,
        openapi_url=None,
        docs_url=None,
        redoc_url=None,
    )
    app.dependency_overrides[get_settings] = lambda: app_settings

    app.include_router(meta_router, prefix="/api/v1")
    app.include_router(auth_router, prefix="/api/v1")
    app.state.pin_store = PinStore()
    # Tight login bucket (SPEC §9): 10 attempts per client IP, refilling 10/min.
    app.state.login_bucket = TokenBucket(capacity=10, refill_per_second=10 / 60)
    app.add_middleware(SpaFallback, static_dir=app_settings.static_dir)
    return app


class Tasterr(FastAPI):
    """FastAPI with SessionCookieSlide wrapped around the *entire* middleware
    stack. Ordinary `add_middleware` would place it inside Starlette's
    outermost ServerErrorMiddleware, whose fabricated unhandled-500 responses
    would then bypass the cookie refresh."""

    def build_middleware_stack(self) -> ASGIApp:
        return SessionCookieSlide(super().build_middleware_stack())


class SessionCookieSlide:
    """Re-issue the sliding session cookie on the way out, whatever the status.

    require_session flags the refresh on request.state; writing the header
    here instead of in the dependency means every error response — an admin
    gate's 403 up to and including an unhandled 500 — still slides, and any
    response that sets the session cookie itself (login's fresh token,
    logout's deletion) wins outright — the same cookie name is never sent
    twice (RFC 6265).
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_refresh(message: Message) -> None:
            if message["type"] == "http.response.start":
                token = cast("str | None", scope.get("state", {}).get("session_cookie_refresh"))
                if token is not None:
                    headers = MutableHeaders(scope=message)
                    prefix = f"{COOKIE_NAME}="
                    if not any(v.startswith(prefix) for v in headers.getlist("set-cookie")):
                        headers.append(
                            "set-cookie",
                            session_cookie_header(token, secure=scope.get("scheme") == "https"),
                        )
            await send(message)

        await self.app(scope, receive, send_with_refresh)


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

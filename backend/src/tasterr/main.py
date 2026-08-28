"""App factory and lifespan: migrate on boot, serve the API and the SPA."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from sqlalchemy.ext.asyncio import async_sessionmaker
from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from tasterr.api.admin import router as admin_router
from tasterr.api.auth import router as auth_router
from tasterr.api.availability import router as availability_router
from tasterr.api.home import router as home_router
from tasterr.api.meta import router as meta_router
from tasterr.api.onboarding import router as onboarding_router
from tasterr.api.recommendations import router as recommendations_router
from tasterr.api.request import router as request_router
from tasterr.api.search import router as search_router
from tasterr.api.signals import router as signals_router
from tasterr.api.title import router as title_router
from tasterr.auth.cookies import COOKIE_NAME, session_cookie_header
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import sweep_expired
from tasterr.cache import Cache
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.http import create_http_client
from tasterr.clients.tmdb import CatalogNotConfigured
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.settings import Settings, get_settings

CONTENT_SECURITY_POLICY = (
    "default-src 'self'; "
    "base-uri 'self'; "
    "object-src 'none'; "
    "frame-ancestors 'none'; "
    "script-src 'self'; "
    "style-src 'self'; "
    "img-src 'self' data: https://image.tmdb.org; "
    "connect-src 'self'; "
    "frame-src https://www.youtube.com; "
    "font-src 'self' data:; "
    "form-action 'self'"
)
SECURITY_HEADERS = {
    "content-security-policy": CONTENT_SECURITY_POLICY,
    "x-frame-options": "DENY",
    "x-content-type-options": "nosniff",
    "referrer-policy": "strict-origin-when-cross-origin",
    "permissions-policy": "camera=(), geolocation=(), microphone=()",
}
HSTS = "max-age=31536000"


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
    app.include_router(admin_router, prefix="/api/v1")
    app.include_router(home_router, prefix="/api/v1")
    app.include_router(title_router, prefix="/api/v1")
    app.include_router(search_router, prefix="/api/v1")
    app.include_router(availability_router, prefix="/api/v1")
    app.include_router(request_router, prefix="/api/v1")
    app.include_router(signals_router, prefix="/api/v1")
    app.include_router(onboarding_router, prefix="/api/v1")
    app.include_router(recommendations_router, prefix="/api/v1")
    app.state.pin_store = PinStore()
    # Tight login bucket (SPEC §9): 10 attempts per client IP, refilling 10/min.
    app.state.login_bucket = TokenBucket(capacity=10, refill_per_second=10 / 60)
    # Loose authenticated mutation bucket: per-user, shared across ordinary writes.
    app.state.mutation_bucket = TokenBucket(capacity=60, refill_per_second=60 / 60)
    app.state.admin_bucket = TokenBucket(capacity=30, refill_per_second=30 / 60)
    app.state.catalog_cache = Cache()
    # A separate bounded cache for short-TTL Seerr availability reads, so they
    # never evict the longer-lived TMDB entries (and vice versa).
    app.state.seerr_cache = Cache()
    # Cold-start seed bookkeeping (M4): per-user single-flight + strong refs
    # so fire-and-forget seed tasks aren't garbage-collected mid-import.
    app.state.seeding = set()
    app.state.seed_tasks = set()
    # Per-user Plex history tasks are both the single-flight claims and the
    # strong references reset uses to cancel/await an in-flight import.
    app.state.plex_history_tasks = {}
    app.state.plex_history_resets = set()
    # Catalog failures map to generic browser errors (no upstream detail leaks).
    # UpstreamRejected (TMDB 4xx) that an endpoint doesn't handle itself (title/
    # detail maps its own 404) also degrades to a generic 502.
    app.add_exception_handler(CatalogNotConfigured, _catalog_unconfigured)
    app.add_exception_handler(UpstreamUnavailable, _catalog_unavailable)
    app.add_exception_handler(UpstreamRejected, _catalog_unavailable)
    app.add_middleware(SpaFallback, static_dir=app_settings.static_dir)
    return app


async def _catalog_unconfigured(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": "Catalog unavailable"})


async def _catalog_unavailable(_request: Request, _exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=502, content={"detail": "Catalog service unavailable"})


class Tasterr(FastAPI):
    """FastAPI with SessionCookieSlide wrapped around the *entire* middleware
    stack. Ordinary `add_middleware` would place it inside Starlette's
    outermost ServerErrorMiddleware, whose fabricated unhandled-500 responses
    would then bypass the cookie refresh."""

    def build_middleware_stack(self) -> ASGIApp:
        return SecurityHeaders(SessionCookieSlide(super().build_middleware_stack()))


class SecurityHeaders:
    """Apply the fixed browser policy outside every HTTP response path."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                message.setdefault("headers", [])
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    headers[name] = value
                if scope.get("scheme") == "https":
                    headers["strict-transport-security"] = HSTS
            await send(message)

        await self.app(scope, receive, send_with_headers)


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
                    message.setdefault("headers", [])
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

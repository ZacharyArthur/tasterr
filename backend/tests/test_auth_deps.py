# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts. Probe routes are
# registered via decorator, not called directly.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnusedFunction=false
import asyncio
from datetime import timedelta
from http.cookies import SimpleCookie
from pathlib import Path
from typing import Annotated, cast

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.factories import user_with_links
from tests.test_account_api import db_call

from tasterr.auth.cookies import COOKIE_NAME
from tasterr.auth.deps import AuthedSession, require_admin, require_same_origin, require_session
from tasterr.auth.sessions import SESSION_ABSOLUTE_TTL, SESSION_TTL, hash_token, new_token
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import UserSession, utcnow
from tasterr.main import create_app
from tasterr.settings import Settings


def _probe_app(tmp_path: Path) -> FastAPI:
    settings = Settings.model_validate(
        {"database_path": tmp_path / "tasterr.db", "static_dir": tmp_path / "static"}
    )
    app = create_app(settings)
    router = APIRouter()

    @router.get("/api/v1/probe/session")
    def probe_session(authed: Annotated[AuthedSession, Depends(require_session)]) -> dict[str, int]:
        return {"user_id": authed.user.id}

    @router.get("/api/v1/probe/admin")
    def probe_admin(authed: Annotated[AuthedSession, Depends(require_admin)]) -> dict[str, int]:
        return {"user_id": authed.user.id}

    @router.post("/api/v1/probe/mutate", dependencies=[Depends(require_same_origin)])
    def probe_mutate() -> dict[str, bool]:
        return {"ok": True}

    @router.get("/api/v1/probe/boom")
    def probe_boom(_: Annotated[AuthedSession, Depends(require_session)]) -> dict[str, bool]:
        raise RuntimeError("unhandled crash after auth")

    app.include_router(router)
    return app


def _seed_session(
    tmp_path: Path, *, is_admin: bool = False, expired: bool = False, stale: bool = False
) -> str:
    """Create a user + session directly in the SQLite file; returns the raw token.
    `stale` backdates last activity past the slide threshold."""

    async def _run() -> str:
        engine = create_engine(tmp_path / "tasterr.db")
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = await user_with_links(
                    db,
                    seerr_user_id=7,
                    display_name="Alice",
                    avatar_url=None,
                    auth_type="plex",
                    is_admin=is_admin,
                )
                await db.flush()
                token = new_token()
                now = utcnow()
                expires = now - timedelta(seconds=5) if expired else now + SESSION_TTL
                last_seen = now - timedelta(hours=2) if stale else now
                db.add(
                    UserSession(
                        token_hash=hash_token(token),
                        user_id=user.id,
                        created_at=now,
                        expires_at=expires,
                        last_seen_at=last_seen,
                    )
                )
                await db.commit()
                return token
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_session_gate_rejects_missing_cookie(tmp_path: Path) -> None:
    with TestClient(_probe_app(tmp_path)) as client:
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 401


def test_session_gate_rejects_garbage_token(tmp_path: Path) -> None:
    with TestClient(_probe_app(tmp_path)) as client:
        client.cookies.set(COOKIE_NAME, "not-a-real-token")
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 401


def test_session_gate_rejects_expired_token(tmp_path: Path) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, expired=True)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 401


def test_session_gate_passes_valid_token(tmp_path: Path) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 200
    assert response.json() == {"user_id": 1}


def _assert_refreshed_cookie(header: str, token: str) -> None:
    assert header.startswith(f"{COOKIE_NAME}={token}")
    max_age = int(SimpleCookie(header)[COOKIE_NAME]["max-age"])
    lifetime = int(SESSION_TTL.total_seconds())
    assert lifetime - 60 < max_age <= lifetime


def test_stale_session_gets_a_refreshed_cookie(tmp_path: Path) -> None:
    """When the server-side window slides, the cookie's Max-Age must slide too."""
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, stale=True)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 200
    _assert_refreshed_cookie(cast("str", response.headers["set-cookie"]), token)


def test_stale_session_refresh_survives_error_responses(tmp_path: Path) -> None:
    """A 403 from the admin gate must still carry the slid cookie refresh —
    the DB slide and the browser cookie must never diverge."""
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, stale=True)  # seeded non-admin

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/admin")

    assert response.status_code == 403
    _assert_refreshed_cookie(cast("str", response.headers["set-cookie"]), token)


def test_stale_session_refresh_survives_unhandled_500(tmp_path: Path) -> None:
    """Even a crash response carries the refresh: SessionCookieSlide wraps
    outside the server-error boundary, so ServerErrorMiddleware's fabricated
    500 still flows through it."""
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, stale=True)

    with TestClient(app, raise_server_exceptions=False) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/boom")

    assert response.status_code == 500
    assert response.headers["content-security-policy"].startswith("default-src 'self'")
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["x-content-type-options"] == "nosniff"
    _assert_refreshed_cookie(cast("str", response.headers["set-cookie"]), token)


def test_fresh_session_gets_no_cookie_churn(tmp_path: Path) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/session")

    assert response.status_code == 200
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize(
    "path,status",
    [("/probe/session", 200), ("/probe/admin", 403), ("/probe/boom", 500)],
)
def test_absolute_expiry_401_and_cookie_refresh_cap(tmp_path: Path, path: str, status: int) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, stale=True)
    db_path = tmp_path / "tasterr.db"

    async def near_cap(db: AsyncSession) -> None:
        session = (await db.scalars(select(UserSession))).one()
        session.created_at = utcnow() - SESSION_ABSOLUTE_TTL + timedelta(seconds=60)

    async def at_cap(db: AsyncSession) -> None:
        session = (await db.scalars(select(UserSession))).one()
        session.created_at = utcnow() - SESSION_ABSOLUTE_TTL
        session.expires_at = utcnow() + SESSION_TTL

    async def no_sessions(db: AsyncSession) -> None:
        assert (await db.scalars(select(UserSession))).all() == []

    with TestClient(app, raise_server_exceptions=False) as client:
        db_call(db_path, near_cap)
        client.cookies.set(COOKIE_NAME, token)
        response = client.get(f"/api/v1{path}")
        assert response.status_code == status
        cookie = SimpleCookie(cast("str", response.headers["set-cookie"]))
        assert 0 < int(cookie[COOKIE_NAME]["max-age"]) <= 60
        db_call(db_path, at_cap)
        expired = client.get(f"/api/v1{path}")
        assert expired.status_code == 401
        assert "set-cookie" not in expired.headers
        db_call(db_path, no_sessions)


def test_admin_gate_rejects_non_admin(tmp_path: Path) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, is_admin=False)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/admin")

    assert response.status_code == 403


def test_admin_gate_passes_admin(tmp_path: Path) -> None:
    app = _probe_app(tmp_path)
    token = _seed_session(tmp_path, is_admin=True)

    with TestClient(app) as client:
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/api/v1/probe/admin")

    assert response.status_code == 200


def test_same_origin_allows_headerless_non_browser_client(tmp_path: Path) -> None:
    with TestClient(_probe_app(tmp_path)) as client:
        response = client.post("/api/v1/probe/mutate")

    assert response.status_code == 200


def test_same_origin_honors_fetch_metadata(tmp_path: Path) -> None:
    with TestClient(_probe_app(tmp_path)) as client:
        for site, expected in (
            ("same-origin", 200),
            ("none", 200),
            ("same-site", 403),
            ("cross-site", 403),
        ):
            response = client.post("/api/v1/probe/mutate", headers={"Sec-Fetch-Site": site})
            assert response.status_code == expected, site


def test_same_origin_falls_back_to_origin_header(tmp_path: Path) -> None:
    with TestClient(_probe_app(tmp_path)) as client:
        matching = client.post("/api/v1/probe/mutate", headers={"Origin": "http://testserver"})
        mismatched = client.post("/api/v1/probe/mutate", headers={"Origin": "https://evil.example"})
        opaque = client.post("/api/v1/probe/mutate", headers={"Origin": "null"})

    assert matching.status_code == 200
    assert mismatched.status_code == 403
    assert opaque.status_code == 403


def test_origin_fallback_requires_matching_scheme(tmp_path: Path) -> None:
    # http:// origin against an https request is cross-origin even on the same host.
    with TestClient(_probe_app(tmp_path), base_url="https://testserver") as client:
        downgraded = client.post("/api/v1/probe/mutate", headers={"Origin": "http://testserver"})
        matching = client.post("/api/v1/probe/mutate", headers={"Origin": "https://testserver"})

    assert downgraded.status_code == 403
    assert matching.status_code == 200


def test_fetch_metadata_wins_over_origin(tmp_path: Path) -> None:
    # A forged same-origin Origin header cannot override cross-site fetch metadata.
    with TestClient(_probe_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/probe/mutate",
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
        )

    assert response.status_code == 403

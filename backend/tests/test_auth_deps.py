# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts. Probe routes are
# registered via decorator, not called directly.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnusedFunction=false

import asyncio
from datetime import timedelta
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.auth.cookies import COOKIE_NAME
from tasterr.auth.deps import AuthedSession, require_admin, require_same_origin, require_session
from tasterr.auth.sessions import SESSION_TTL, hash_token, new_token
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User, UserSession, utcnow
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

    app.include_router(router)
    return app


def _seed_session(tmp_path: Path, *, is_admin: bool = False, expired: bool = False) -> str:
    """Create a user + session directly in the SQLite file; returns the raw token."""

    async def _run() -> str:
        engine = create_engine(tmp_path / "tasterr.db")
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(
                    seerr_user_id=7,
                    display_name="Alice",
                    avatar_url=None,
                    auth_type="plex",
                    is_admin=is_admin,
                )
                db.add(user)
                await db.flush()
                token = new_token()
                now = utcnow()
                expires = now - timedelta(seconds=5) if expired else now + SESSION_TTL
                db.add(
                    UserSession(
                        token_hash=hash_token(token),
                        user_id=user.id,
                        seerr_cookie="connect.sid=s%3Aseed",
                        plex_token_enc=None,
                        created_at=now,
                        expires_at=expires,
                        last_seen_at=now,
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


def test_fetch_metadata_wins_over_origin(tmp_path: Path) -> None:
    # A forged same-origin Origin header cannot override cross-site fetch metadata.
    with TestClient(_probe_app(tmp_path)) as client:
        response = client.post(
            "/api/v1/probe/mutate",
            headers={"Sec-Fetch-Site": "cross-site", "Origin": "http://testserver"},
        )

    assert response.status_code == 403

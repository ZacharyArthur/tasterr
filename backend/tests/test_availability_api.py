# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.availability import get_availability
from tasterr.auth.sessions import mint_session
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.main import create_app
from tasterr.settings import Settings

SECRET = "test-secret-key"
SEERR_URL = "http://seerr:5055"


def _app(tmp_path: Path, *, seerr: bool = True) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": SECRET,
    }
    if seerr:
        overrides["seerr_internal_url"] = SEERR_URL
        overrides["seerr_api_key"] = "seerr-api-key"
    return create_app(Settings.model_validate(overrides))


def _seed_session(db_path: Path) -> str:
    async def _run() -> str:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(
                    seerr_user_id=99,
                    display_name="Seeded",
                    avatar_url=None,
                    auth_type="local",
                    is_admin=False,
                )
                db.add(user)
                await db.flush()
                return await mint_session(db, user.id, "connect.sid=s%3Aseed", None)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _authed_client(app: FastAPI, db_path: Path) -> TestClient:
    token = _seed_session(db_path)
    client = TestClient(app)
    client.cookies.set("tasterr_session", token)
    return client


def _override(app: FastAPI, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    cache = Cache()

    def dep() -> AvailabilityService:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return AvailabilityService(SeerrClient(http, SEERR_URL, "k"), cache)

    app.dependency_overrides[get_availability] = dep


def test_availability_requires_a_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/availability", json={"items": [{"media_type": "movie", "id": 1}]}
        )
    assert response.status_code == 401


def test_batch_returns_a_status_per_title(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/movie/1":
            return httpx.Response(
                200,
                json={
                    "mediaInfo": {
                        "status": 5,
                        "mediaUrl": "https://app.plex.tv/desktop/#!/details",
                        "iOSPlexUrl": "plex://preplay/?metadataKey=x",
                    }
                },
            )
        return httpx.Response(404, json={})  # movie/2: known, not in library

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.post(
            "/api/v1/availability",
            json={"items": [{"media_type": "movie", "id": 1}, {"media_type": "movie", "id": 2}]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "movie:1": {
            "status": "available",
            "known": True,
            "playback": {
                "regular": {
                    "web_url": "https://app.plex.tv/desktop/#!/details",
                    "app_url": "plex://preplay/?metadataKey=x",
                    "android_intent_url": (
                        "intent://preplay/?metadataKey=x#Intent;scheme=plex;"
                        "package=com.plexapp.android;S.browser_fallback_url="
                        "https%3A%2F%2Fapp.plex.tv%2Fdesktop%2F%23%21%2Fdetails;end"
                    ),
                },
                "four_k": None,
            },
        },
        "movie:2": {"status": "not_requested", "known": True, "playback": None},
    }


def test_one_unresolved_title_does_not_fail_the_batch(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/movie/3":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json={"mediaInfo": {"status": 5}})

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.post(
            "/api/v1/availability",
            json={"items": [{"media_type": "movie", "id": 1}, {"media_type": "movie", "id": 3}]},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["movie:1"] == {"status": "available", "known": True, "playback": None}
    assert body["movie:3"] == {"status": "unknown", "known": False, "playback": None}


def test_unconfigured_seerr_yields_unknown_without_a_call(tmp_path: Path) -> None:
    # Real dependency (no override): unconfigured Seerr → a no-client service that
    # returns Unknown for every title and never opens a connection.
    app = _app(tmp_path, seerr=False)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.post(
            "/api/v1/availability",
            json={"items": [{"media_type": "movie", "id": 1}, {"media_type": "tv", "id": 2}]},
        )

    assert response.status_code == 200
    assert response.json() == {
        "movie:1": {"status": "unknown", "known": False, "playback": None},
        "tv:2": {"status": "unknown", "known": False, "playback": None},
    }


def test_oversize_batch_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _override(app, lambda _: httpx.Response(200, json={"mediaInfo": {"status": 5}}))
    db_path = tmp_path / "tasterr.db"
    items = [{"media_type": "movie", "id": i} for i in range(1, 102)]  # 101 > MAX_BATCH
    with _authed_client(app, db_path) as client:
        response = client.post("/api/v1/availability", json={"items": items})

    assert response.status_code == 422  # bounded input, before any Seerr work

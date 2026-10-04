# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.destinations import get_destinations_client
from tasterr.auth.sessions import mint_session
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.main import create_app
from tasterr.settings import Settings

SEERR_URL = "http://seerr:5055"

SERVER_FIXTURE = {
    "id": 0,
    "name": "radarr",
    "isDefault": True,
    "activeDirectory": "/movies",
    "activeProfileId": 7,
}
DETAIL_FIXTURE = {
    "server": SERVER_FIXTURE,
    "profiles": [{"id": 7, "name": "HD Bluray + WEB"}],
    "rootFolders": [
        {"id": 1, "freeSpace": 1, "path": "/movies"},
        {"id": 2, "freeSpace": 1, "path": "/new releases"},
    ],
}


def _app(tmp_path: Path, *, seerr: bool = True) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": "test-secret-key",
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
    def dep() -> SeerrClient:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return SeerrClient(http, SEERR_URL, "k")

    app.dependency_overrides[get_destinations_client] = dep


def test_destinations_requires_a_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        response = client.get("/api/v1/movie/1/destinations")
    assert response.status_code == 401


def test_single_server_shape(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/service/radarr":
            return httpx.Response(200, json=[SERVER_FIXTURE])
        assert request.url.path == "/api/v1/service/radarr/0"
        return httpx.Response(200, json=DETAIL_FIXTURE)

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    assert response.json() == [
        {
            "server_id": 0,
            "server_name": "radarr",
            "is_default": True,
            "default_profile_id": 7,
            "default_root_folder": "/movies",
            "quality_profiles": [{"id": 7, "name": "HD Bluray + WEB"}],
            "root_folders": [{"id": 1, "path": "/movies"}, {"id": 2, "path": "/new releases"}],
        }
    ]


def test_multi_server_shape(tmp_path: Path) -> None:
    second_server = {**SERVER_FIXTURE, "id": 1, "name": "radarr-4k", "isDefault": False}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/service/radarr":
            return httpx.Response(200, json=[SERVER_FIXTURE, second_server])
        return httpx.Response(
            200,
            json={**DETAIL_FIXTURE, "server": second_server}
            if request.url.path == "/api/v1/service/radarr/1"
            else DETAIL_FIXTURE,
        )

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 2
    assert {d["server_id"] for d in body} == {0, 1}


def test_unconfigured_seerr_yields_empty_list_without_a_call(tmp_path: Path) -> None:
    app = _app(tmp_path, seerr=False)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    assert response.json() == []


def test_seerr_down_yields_empty_list(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    assert response.json() == []


def test_one_server_detail_failure_still_returns_the_rest(tmp_path: Path) -> None:
    second_server = {**SERVER_FIXTURE, "id": 1, "name": "radarr-4k"}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/service/radarr":
            return httpx.Response(200, json=[SERVER_FIXTURE, second_server])
        if request.url.path == "/api/v1/service/radarr/1":
            return httpx.Response(500, text="down")
        return httpx.Response(200, json=DETAIL_FIXTURE)

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["server_id"] == 0

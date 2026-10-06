# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Callable
from pathlib import Path

import httpx
import pytest
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


def _override(
    app: FastAPI, handler: Callable[[httpx.Request], httpx.Response], *, permissions: int = 2
) -> None:
    def dep() -> SeerrClient:
        def wrapped(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/api/v1/user/99":
                return httpx.Response(200, json={"id": 99, "permissions": permissions})
            return handler(request)

        http = httpx.AsyncClient(transport=httpx.MockTransport(wrapped))
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
    assert response.json() == {
        "available": True,
        "can_request_standard": True,
        "can_request_4k": False,
        "can_request_4k_default": False,
        "can_override": True,
        "can_request_specials": False,
        "can_request_partial": False,
        "destinations": [
            {
                "server_id": 0,
                "server_name": "radarr",
                "is_default": True,
                "is_4k": False,
                "default_profile_id": 7,
                "default_root_folder": "/movies",
                "quality_profiles": [{"id": 7, "name": "HD Bluray + WEB"}],
                "root_folders": [{"id": 1, "path": "/movies"}, {"id": 2, "path": "/new releases"}],
            }
        ],
    }


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
    body = response.json()["destinations"]
    assert len(body) == 2
    assert {d["server_id"] for d in body} == {0, 1}


def test_unconfigured_seerr_yields_empty_list_without_a_call(tmp_path: Path) -> None:
    app = _app(tmp_path, seerr=False)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "can_request_standard": False,
        "can_request_4k": False,
        "can_request_4k_default": False,
        "can_override": False,
        "can_request_specials": False,
        "can_request_partial": False,
        "destinations": [],
    }


def test_seerr_down_yields_empty_list(tmp_path: Path) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="down")

    app = _app(tmp_path)
    _override(app, handler)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/movie/42/destinations")

    assert response.status_code == 200
    assert response.json() == {
        "available": False,
        "can_request_standard": False,
        "can_request_4k": False,
        "can_request_4k_default": False,
        "can_override": False,
        "can_request_specials": False,
        "can_request_partial": False,
        "destinations": [],
    }


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
    body = response.json()["destinations"]
    assert len(body) == 1
    assert body[0]["server_id"] == 0


@pytest.mark.parametrize(
    "permission,variant_ids,can_4k,advanced",
    [
        (2, {0, 1}, True, True),
        (32 | 8192, {0}, False, True),
        (2048 | 8192, {1}, True, True),
        (32 | 2048, set(), True, False),
        (16, set(), False, True),
        (4096 | 8192, set(), False, True),
    ],
)
def test_discovery_scopes_variant_metadata(
    tmp_path: Path, permission: int, variant_ids: set[int], can_4k: bool, advanced: bool
) -> None:
    four_k = {**SERVER_FIXTURE, "id": 1, "is4k": True}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/service/radarr":
            return httpx.Response(200, json=[four_k, SERVER_FIXTURE])
        server = four_k if request.url.path.endswith("/1") else SERVER_FIXTURE
        return httpx.Response(200, json={**DETAIL_FIXTURE, "server": server})

    app = _app(tmp_path)
    _override(app, handler, permissions=permission)
    with _authed_client(app, tmp_path / "tasterr.db") as client:
        body = client.get("/api/v1/movie/42/destinations").json()
    assert body["can_override"] is advanced
    assert body["can_request_4k"] is can_4k
    assert {d["server_id"] for d in body["destinations"]} == variant_ids
    assert all(d["is_4k"] == (d["server_id"] == 1) for d in body["destinations"])


@pytest.mark.parametrize("advanced", [False, True])
@pytest.mark.parametrize("configuration", ["empty", "standard", "nondefault", "default"])
def test_4k_discovery_requires_a_default_or_advanced_destination(
    tmp_path: Path, advanced: bool, configuration: str
) -> None:
    servers = (
        []
        if configuration == "empty"
        else [
            {
                **SERVER_FIXTURE,
                "is4k": configuration != "standard",
                "isDefault": configuration != "nondefault",
            }
        ]
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/service/radarr":
            return httpx.Response(200, json=servers)
        return httpx.Response(200, json={**DETAIL_FIXTURE, "server": servers[0]})

    app = _app(tmp_path)
    _override(app, handler, permissions=2048 | (8192 if advanced else 0))
    with _authed_client(app, tmp_path / "tasterr.db") as client:
        body = client.get("/api/v1/movie/42/destinations").json()
    allowed = configuration == "default" or (advanced and configuration == "nondefault")
    assert body["can_request_4k"] is allowed
    assert body["can_request_4k_default"] is (configuration == "default")
    assert bool(body["destinations"]) is (advanced and allowed)


@pytest.mark.parametrize(
    "enabled,status,expected", [(True, 200, True), (False, 200, False), (True, 503, False)]
)
@pytest.mark.parametrize("partial", [True, False])
def test_tv_request_policy_preserves_ordinary_destinations(
    tmp_path: Path, enabled: bool, status: int, expected: bool, partial: bool
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/settings/public":
            return httpx.Response(
                status,
                json={
                    "enableSpecialEpisodes": enabled,
                    "partialRequestsEnabled": partial,
                    "ignored": "value",
                },
            )
        if request.url.path == "/api/v1/service/sonarr":
            return httpx.Response(200, json=[SERVER_FIXTURE])
        assert request.url.path == "/api/v1/service/sonarr/0"
        return httpx.Response(200, json=DETAIL_FIXTURE)

    app = _app(tmp_path)
    _override(app, handler)
    with _authed_client(app, tmp_path / "tasterr.db") as client:
        response = client.get("/api/v1/tv/7/destinations")
    assert response.status_code == 200
    body = response.json()
    assert body["can_request_specials"] is (expected and partial)
    assert body["can_request_partial"] is (partial and status == 200)
    assert body["available"] and body["can_request_standard"]
    assert len(body["destinations"]) == 1
    assert not {"ignored", "enableSpecialEpisodes", "partialRequestsEnabled"} & body.keys()

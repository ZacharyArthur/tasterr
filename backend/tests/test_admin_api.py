# starlette's TestClient ships partially-unknown method annotations.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from pathlib import Path
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.admin import router as admin_router
from tasterr.api.availability import get_availability
from tasterr.api.catalog import get_catalog
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.models import RegionOption, ServiceOption
from tasterr.catalog.service import CatalogService
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.main import create_app
from tasterr.settings import Settings

SECRET = "test-secret-key"


class FakeAdminCatalog:
    def __init__(self) -> None:
        self.service_calls: list[str] = []

    async def regions(self) -> list[RegionOption]:
        return [RegionOption(code="GB", name="United Kingdom")]

    async def services(self, region: str | None = None) -> list[ServiceOption]:
        assert region is not None
        self.service_calls.append(region)
        return [
            ServiceOption(
                provider_id=8,
                name="Netflix",
                logo_path="/n.png",
                display_priority=1,
            )
        ]


def _app(tmp_path: Path) -> FastAPI:
    return create_app(
        Settings.model_validate(
            {
                "database_path": tmp_path / "tasterr.db",
                "static_dir": tmp_path / "static",
                "tasterr_secret_key": SECRET,
                "tmdb_api_key": "tmdb-key",
                "seerr_internal_url": "http://seerr:5055",
                "seerr_api_key": "seerr-key",
            }
        )
    )


def _seed_session(db_path: Path, *, is_admin: bool) -> str:
    async def run() -> str:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(
                    seerr_user_id=1 if is_admin else 2,
                    display_name="Admin" if is_admin else "Member",
                    auth_type="local",
                    is_admin=is_admin,
                )
                db.add(user)
                await db.flush()
                return await mint_session(db, user.id, "connect.sid=test", None)
        finally:
            await engine.dispose()

    return asyncio.run(run())


def _client(app: FastAPI, db_path: Path, *, is_admin: bool = True) -> TestClient:
    client = TestClient(app)
    client.cookies.set("tasterr_session", _seed_session(db_path, is_admin=is_admin))
    return client


def test_settings_endpoints_are_default_deny(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with TestClient(app) as anonymous:
        assert anonymous.get("/api/v1/settings").status_code == 401
    with _client(app, db_path, is_admin=False) as member:
        assert member.get("/api/v1/settings").status_code == 403
        assert member.put("/api/v1/settings", json={}).status_code == 403


def test_admin_settings_default_and_round_trip(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        default = client.get("/api/v1/settings")
        saved = client.put(
            "/api/v1/settings",
            json={
                "region": "gb",
                "service_ids": [8, 337],
                "disabled_rail_types": ["hero", "genres"],
                "appearance": {"theme": "light", "accent": "azure"},
            },
        )
        reread = client.get("/api/v1/settings")

    assert default.status_code == 200
    assert default.json()["settings"]["region"] == "US"
    assert {item["id"] for item in default.json()["rail_types"]} >= {"hero", "services"}
    assert saved.status_code == 200
    assert saved.json()["settings"] == reread.json()["settings"]
    assert reread.json()["settings"]["region"] == "GB"
    assert reread.json()["settings"]["appearance"] == {"theme": "light", "accent": "azure"}


def test_invalid_settings_do_not_replace_previous_value(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        assert client.put("/api/v1/settings", json={"region": "GB"}).status_code == 200
        invalid = client.put("/api/v1/settings", json={"region": "USA"})
        current = client.get("/api/v1/settings").json()["settings"]

    assert invalid.status_code == 422
    assert current["region"] == "GB"


def test_settings_save_rejects_cross_origin_and_rate_limit(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        cross = client.put(
            "/api/v1/settings",
            json={},
            headers={"Sec-Fetch-Site": "cross-site"},
        )
        app.state.admin_bucket = TokenBucket(capacity=1, refill_per_second=0)
        first = client.put("/api/v1/settings", json={})
        second = client.put("/api/v1/settings", json={})

    assert cross.status_code == 403
    assert first.status_code == 200
    assert second.status_code == 429


def test_rejected_non_admin_does_not_spend_admin_mutation_capacity(
    tmp_path: Path,
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    member_token = _seed_session(db_path, is_admin=False)
    admin_token = _seed_session(db_path, is_admin=True)
    app.state.admin_bucket = TokenBucket(capacity=1, refill_per_second=0)

    with TestClient(app) as client:
        client.cookies.set("tasterr_session", member_token)
        rejected = client.put("/api/v1/settings", json={})
        client.cookies.set("tasterr_session", admin_token)
        accepted = client.put("/api/v1/settings", json={})

    assert rejected.status_code == 403
    assert accepted.status_code == 200


def test_admin_mutation_uses_only_the_admin_user_bucket(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    app.state.admin_bucket = TokenBucket(capacity=1, refill_per_second=0)
    app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)

    with _client(app, db_path) as client:
        accepted = client.put("/api/v1/settings", json={})

    assert accepted.status_code == 200
    assert set(app.state.admin_bucket._buckets) == {"1"}  # pyright: ignore[reportPrivateUsage]
    assert app.state.mutation_bucket._buckets == {}  # pyright: ignore[reportPrivateUsage]


def test_regions_and_services_are_admin_only_and_validated(tmp_path: Path) -> None:
    fake = FakeAdminCatalog()
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", fake)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        regions = client.get("/api/v1/regions")
        services = client.get("/api/v1/services?region=gb")
        invalid = client.get("/api/v1/services?region=USA")

    assert regions.json() == {"regions": [{"code": "GB", "name": "United Kingdom"}]}
    assert services.json()["region"] == "GB"
    assert services.json()["services"][0]["provider_id"] == 8
    assert invalid.status_code == 422
    assert fake.service_calls == ["GB"]


def test_connection_tests_are_typed_and_generic(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/3/configuration":
            return httpx.Response(200, json={"images": {}})
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json={"version": "3.3.0"})
        raise AssertionError(request.url.path)

    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        tmdb = client.post("/api/v1/connection-test", json={"target": "tmdb"})
        seerr = client.post("/api/v1/connection-test", json={"target": "seerr"})
        invalid = client.post("/api/v1/connection-test", json={"target": "custom"})

    assert tmdb.json() == {"target": "tmdb", "ok": True, "detail": "Connection successful"}
    assert seerr.json() == {
        "target": "seerr",
        "ok": True,
        "detail": "Connection successful",
    }
    assert invalid.status_code == 422


def test_connection_failure_leaks_no_upstream_detail(tmp_path: Path) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("SENTINEL-UPSTREAM http://seerr:5055", request=request)

    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        response = client.post("/api/v1/connection-test", json={"target": "seerr"})
        health = client.get("/api/v1/health")

    assert response.json() == {
        "target": "seerr",
        "ok": False,
        "detail": "Connection failed",
    }
    assert "SENTINEL" not in response.text
    assert "seerr:5055" not in response.text
    assert health.status_code == 200


def test_admin_openapi_models_are_secret_free(tmp_path: Path) -> None:
    schema = _app(tmp_path).openapi()
    rendered = str(schema["paths"])
    assert "/api/v1/settings" in schema["paths"]
    assert "/api/v1/connection-test" in schema["paths"]
    for forbidden in ("api_key", "internal_url", "secret", "cookie", "credential"):
        assert forbidden not in rendered.lower()


def test_every_admin_route_declares_an_explicit_response_model() -> None:
    routes = [route for route in admin_router.routes if isinstance(route, APIRoute)]
    assert len(routes) == 5
    assert all(route.response_model is not None for route in routes)


def test_saved_settings_change_later_browse_requests_without_restart(tmp_path: Path) -> None:
    seen: list[httpx.URL] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url)
        if request.url.path == "/3/discover/movie":
            assert request.url.params["watch_region"] == "GB"
            assert request.url.params["with_watch_providers"] == "8"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "id": item,
                            "title": f"Title {item}",
                            "backdrop_path": f"/b{item}.jpg",
                        }
                        for item in range(1, 8)
                    ]
                },
            )
        if request.url.path.startswith("/3/movie/"):
            tmdb_id = int(request.url.path.rsplit("/", 1)[1])
            assert request.url.params["region"] == "GB"
            return httpx.Response(
                200,
                json={
                    "id": tmdb_id,
                    "title": f"Title {tmdb_id}",
                    "backdrop_path": f"/b{tmdb_id}.jpg",
                    "release_dates": {
                        "results": [
                            {
                                "iso_3166_1": "GB",
                                "release_dates": [{"certification": "12"}],
                            }
                        ]
                    },
                },
            )
        raise AssertionError(str(request.url))

    app = _app(tmp_path)
    app.dependency_overrides[get_availability] = lambda: AvailabilityService(None, Cache())
    db_path = tmp_path / "tasterr.db"
    with _client(app, db_path) as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        saved = client.put(
            "/api/v1/settings",
            json={
                "region": "GB",
                "service_ids": [8],
                "disabled_rail_types": [
                    "trending",
                    "recent",
                    "my-list",
                    "recommended",
                    "more-like",
                    "services",
                    "genres",
                    "top-rated",
                    "decades",
                ],
            },
        )
        home = client.get("/api/v1/home")
        extra = client.get("/api/v1/rails")
        detail = client.get("/api/v1/title/movie/1")

    assert saved.status_code == 200
    assert [rail["id"] for rail in home.json()["rails"]] == ["popular"]
    assert extra.json() == {"rails": [], "next_cursor": None}
    assert detail.json()["certification"] == "12"
    assert any(url.path == "/3/discover/movie" for url in seen)

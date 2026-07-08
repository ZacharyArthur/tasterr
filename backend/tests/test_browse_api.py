# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.availability import get_availability
from tasterr.api.catalog import get_catalog
from tasterr.auth.sessions import mint_session
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.models import Genre, MediaDetail, MediaSummary, WatchProviders
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.main import create_app
from tasterr.settings import Settings

SECRET = "test-secret-key"


def _summary(i: int) -> MediaSummary:
    return MediaSummary(
        id=i,
        media_type="movie",
        title=f"T{i}",
        overview="",
        poster_path=None,
        backdrop_path="/b.jpg",
        year=2020,
        vote_average=7.0,
    )


def _detail(i: int) -> MediaDetail:
    return MediaDetail(
        id=i,
        media_type="movie",
        title=f"T{i}",
        overview="",
        poster_path=None,
        backdrop_path="/b.jpg",
        year=2020,
        vote_average=7.0,
        tagline="",
        genres=[Genre(id=18, name="Drama")],
        runtime=100,
        release_date="2020-01-01",
        certification="PG-13",
        logo_path="/logo.png",
        trailer=None,
        cast=[],
        crew=[],
        watch=WatchProviders(),
        recommendations=[],
        similar=[],
        seasons=[],
        number_of_seasons=None,
    )


class FakeCatalog:
    region = "US"

    def __init__(self) -> None:
        self.fail = False
        self.fail_trending = False
        self.reject_search = False
        self.unknown_ids: set[int] = set()
        self._block = 100

    async def trending(self) -> list[MediaSummary]:
        if self.fail or self.fail_trending:
            raise UpstreamUnavailable("down")
        return [_summary(i) for i in range(1, 7)]

    async def discover(self, media: str, **_: object) -> list[MediaSummary]:
        if self.fail:
            raise UpstreamUnavailable("down")
        block = self._block
        self._block += 100
        return [_summary(block + i) for i in range(10)]

    async def genre_map(self, media: str) -> dict[str, int]:
        if self.fail:
            raise UpstreamUnavailable("down")
        return {"Action": 28, "Comedy": 35, "Drama": 18, "Thriller": 53}

    async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
        if tmdb_id in self.unknown_ids:
            raise UpstreamRejected(404)
        if self.fail:
            raise UpstreamUnavailable("down")
        return _detail(tmdb_id)

    async def search(self, query: str) -> list[MediaSummary]:
        if not query.strip():
            return []
        if self.reject_search:
            raise UpstreamRejected(401)
        if self.fail:
            raise UpstreamUnavailable("down")
        return [_summary(1), _summary(2)]


def _app(tmp_path: Path, *, tmdb: bool = True) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": SECRET,
        "seerr_internal_url": "http://seerr:5055",
        "seerr_api_key": "seerr-api-key",
    }
    if tmdb:
        overrides["tmdb_api_key"] = "tmdb-key"
    app = create_app(Settings.model_validate(overrides))
    # Default browse tests exercise the catalog, not Seerr — give them a no-client
    # availability service so title detail never makes a live Seerr call. Tests that
    # assert availability re-override get_availability with a mock-backed client.
    app.dependency_overrides[get_availability] = lambda: AvailabilityService(None, Cache())
    return app


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


# ── Session gating (4.1-4.3) ─────────────────────────────────────────────────


def test_browse_endpoints_require_a_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    with TestClient(app) as client:
        assert client.get("/api/v1/home").status_code == 401
        assert client.get("/api/v1/rails").status_code == 401
        assert client.get("/api/v1/title/movie/42").status_code == 401
        assert client.get("/api/v1/search?q=x").status_code == 401


# ── Home + rails (4.1) ───────────────────────────────────────────────────────


def test_home_returns_hero_and_rails(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/home")

    assert response.status_code == 200
    body = response.json()
    assert len(body["hero"]) > 0
    assert len(body["rails"]) > 0


def test_home_degrades_when_a_provider_fails(tmp_path: Path) -> None:
    fake = FakeCatalog()
    fake.fail_trending = True
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", fake)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/home")

    assert response.status_code == 200
    rail_ids = {rail["id"] for rail in response.json()["rails"]}
    assert "trending" not in rail_ids
    assert "popular" in rail_ids


def test_rails_paginate_with_cursor(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        first = client.get("/api/v1/rails?cursor=0").json()
        deep = client.get("/api/v1/rails?cursor=8").json()

    assert first["next_cursor"] == 4
    assert deep["next_cursor"] is None  # catalogue exhausted


# ── Title detail (4.2) ───────────────────────────────────────────────────────


def test_title_detail_returns_media_detail(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/42")

    assert response.status_code == 200
    assert response.json()["id"] == 42


def test_title_invalid_type_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/book/42")

    assert response.status_code == 422  # Literal path validation, before any upstream call


def test_title_unknown_id_is_generic_404(tmp_path: Path) -> None:
    fake = FakeCatalog()
    fake.unknown_ids = {999}
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", fake)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/999")

    assert response.status_code == 404
    assert response.json() == {"detail": "Title not found"}


def _override_availability(
    app: FastAPI, handler: Callable[[httpx.Request], httpx.Response]
) -> None:
    cache = Cache()

    def dep() -> AvailabilityService:
        http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        return AvailabilityService(SeerrClient(http, "http://seerr:5055", "k"), cache)

    app.dependency_overrides[get_availability] = dep


def test_title_detail_includes_availability(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    _override_availability(app, lambda _: httpx.Response(200, json={"mediaInfo": {"status": 5}}))
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/42")

    assert response.status_code == 200
    assert response.json()["availability"] == {"status": "available", "known": True}


def test_title_availability_degrades_when_seerr_down(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    _override_availability(app, lambda _: httpx.Response(503, text="down"))
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/42")

    # Seerr down never fails or blanks the detail — availability just reads Unknown.
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == 42
    assert body["availability"] == {"status": "unknown", "known": False}


# ── Search (4.3) ─────────────────────────────────────────────────────────────


def test_search_returns_results(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/search?q=deep")

    assert response.status_code == 200
    assert [r["id"] for r in response.json()["results"]] == [1, 2]


def test_empty_search_returns_no_results(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/search")

    assert response.status_code == 200
    assert response.json() == {"results": []}


# ── Degradation (4.4) ────────────────────────────────────────────────────────


def test_unconfigured_tmdb_returns_503_and_health_stays_up(tmp_path: Path) -> None:
    app = _app(tmp_path, tmdb=False)  # no override: exercise the real dependency guard
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        home = client.get("/api/v1/home")
        health = client.get("/api/v1/health")

    assert home.status_code == 503
    assert home.json() == {"detail": "Catalog unavailable"}
    assert health.status_code == 200


def test_unauthenticated_takes_priority_over_unconfigured(tmp_path: Path) -> None:
    # Default-deny: an anonymous caller gets 401 even when TMDB is unconfigured —
    # the 503 must never leak configuration state to unauthenticated traffic.
    app = _app(tmp_path, tmdb=False)  # real get_catalog, which now requires a session
    with TestClient(app) as client:
        assert client.get("/api/v1/home").status_code == 401
        assert client.get("/api/v1/search?q=x").status_code == 401


def test_search_upstream_rejection_is_generic_502(tmp_path: Path) -> None:
    fake = FakeCatalog()
    fake.reject_search = True  # TMDB 4xx (e.g. revoked key) on search
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", fake)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/search?q=x")

    assert response.status_code == 502
    assert response.json() == {"detail": "Catalog service unavailable"}


def test_upstream_failure_is_generic_502(tmp_path: Path) -> None:
    fake = FakeCatalog()
    fake.fail = True
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", fake)
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        home = client.get("/api/v1/home")
        search = client.get("/api/v1/search?q=x")
        title = client.get("/api/v1/title/movie/42")

    assert home.status_code == search.status_code == title.status_code == 502
    assert home.json() == {"detail": "Catalog service unavailable"}
    assert "down" not in search.text  # no upstream detail leaks

# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Never, cast

import httpx
import pytest
from cryptography.fernet import InvalidToken
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.availability import get_availability
from tasterr.api.catalog import get_catalog
from tasterr.api.runtime_settings import get_runtime_settings
from tasterr.api.title import get_title
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.deps import AuthedSession
from tasterr.auth.sessions import mint_session
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.discovery import DiscoveryFilter
from tasterr.catalog.facts import TitleFacts
from tasterr.catalog.models import Genre, MediaDetail, MediaSummary, RailsPage, WatchProviders
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexCloudAccount, PlexServerDiscovery
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User, UserSession
from tasterr.db.runtime_settings import save_runtime_settings
from tasterr.main import create_app
from tasterr.rails.registry import RailContext
from tasterr.recommend.signals import SignalKind
from tasterr.recommend.store import record_signal
from tasterr.runtime_settings import RailType, RuntimeSettings
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
        external_url=f"https://www.themoviedb.org/movie/{i}",
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
    discovery_filter: DiscoveryFilter | None = None
    region = "US"
    selected_service_ids: tuple[int, ...] = ()

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


def test_discovery_filters_home_extra_and_suggestions_but_preserves_access(tmp_path: Path) -> None:
    class ExclusionCatalog(FakeCatalog):
        async def title_facts(self, media: str, tmdb_id: int) -> TitleFacts:
            return TitleFacts(
                tmdb_id=tmdb_id,
                media_type="movie" if media == "movie" else "tv",
                title="Title",
                watch_region="US",
                flatrate_provider_ids=[8] if tmdb_id % 2 else [],
            )

        async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
            return (await super().detail(media, tmdb_id)).model_copy(
                update={
                    "recommendations": [_summary(1), _summary(2)],
                    "similar": [_summary(3), _summary(4)],
                }
            )

    app = _app(tmp_path)

    def catalog_for_request() -> CatalogService:
        catalog = ExclusionCatalog()
        catalog.discovery_filter = DiscoveryFilter(
            cast("CatalogService", catalog), None, False, [8]
        )
        return cast("CatalogService", catalog)

    app.dependency_overrides[get_catalog] = catalog_for_request
    with _authed_client(app, tmp_path / "tasterr.db") as client:
        home = client.get("/api/v1/home")
        extra = client.get("/api/v1/rails")
        detail = client.get("/api/v1/title/movie/1")
        search = client.get("/api/v1/search?q=Title")
    assert home.status_code == extra.status_code == detail.status_code == search.status_code == 200
    assert all(
        item["id"] % 2 == 0
        for rail in home.json()["rails"] + extra.json()["rails"]
        for item in rail["items"]
    )
    assert all(slide["item"]["id"] % 2 == 0 for slide in home.json()["hero"])
    assert [item["id"] for item in detail.json()["recommendations"]] == [2]
    assert [item["id"] for item in detail.json()["similar"]] == [4]
    assert detail.json()["id"] == 1
    assert [item["id"] for item in search.json()["results"]] == [1, 2]


@pytest.mark.parametrize("environment", [False, True])
@pytest.mark.parametrize("mode", ["subscription", "library", "seerr_outage"])
@pytest.mark.parametrize("suggestion_media", ["movie", "tv"])
def test_production_dependencies_apply_stored_and_environment_exclusions(
    tmp_path: Path,
    environment: bool,
    mode: str,
    suggestion_media: str,
) -> None:
    library = mode != "subscription"
    preferences = {"hide_library_items": library, "excluded_service_ids": [] if library else [8]}
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": SECRET,
        "tmdb_api_key": "fixture-key",
        "seerr_internal_url": "http://seerr:5055",
        "seerr_api_key": "fixture-key",
    }
    if environment:
        overrides.update({f"tasterr_{key}": value for key, value in preferences.items()})
    app = create_app(Settings.model_validate(overrides))
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path)
    _record_signals(db_path, ["request", "watchlist"], tmdb_id=1001)
    _record_signals(db_path, ["request"], seerr_user_id=7, tmdb_id=1001)

    async def persist(region: str = "US") -> None:
        engine = create_engine(db_path)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await save_runtime_settings(
                    db,
                    RuntimeSettings.model_validate(
                        {"region": region, **({} if environment else preferences)}
                    ),
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(persist())

    def results(start: int, media: str = "movie") -> list[dict[str, object]]:
        return [
            {
                "id": i,
                "title": f"Title {i}",
                "name": f"Title {i}",
                "media_type": media,
                "backdrop_path": "/fixture.jpg",
            }
            for i in range(start, start + 20)
        ]

    def expected_ids(start: int) -> list[int]:
        return list(
            range(
                start if mode == "seerr_outage" else start + 1,
                start + 20,
                1 if mode == "seerr_outage" else 2,
            )
        )

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if request.url.host == "seerr":
            if mode == "seerr_outage":
                return httpx.Response(401, json={})
            tmdb_id = int(path.rsplit("/", 1)[-1])
            variant = "status" if "/tv/" in path else "status4k"
            return httpx.Response(200, json={"mediaInfo": {variant: 4 if tmdb_id % 2 else 1}})
        if path.endswith("/genre/movie/list") or path.endswith("/genre/tv/list"):
            return httpx.Response(200, json={"genres": [{"id": 18, "name": "Drama"}]})
        if "/trending/" in path or "/search/" in path:
            return httpx.Response(200, json={"results": results(1)})
        if "/discover/" in path:
            assert request.url.params["watch_region"] == "US"
            assert request.url.params["page"] == "1"
            assert "with_watch_providers" not in request.url.params
            sort = request.url.params["sort_by"]
            start = (
                801
                if "primary_release_date.gte" in request.url.params
                else 301
                if sort == "primary_release_date.desc"
                else 501
                if sort == "vote_average.desc" and path.endswith("tv")
                else 401
                if sort == "vote_average.desc"
                else 201
                if path.endswith("tv")
                else 101
            )
            return httpx.Response(
                200,
                json={
                    "total_pages": 1,
                    "results": results(start, "tv" if path.endswith("tv") else "movie"),
                },
            )
        if "/movie/" in path or "/tv/" in path:
            tmdb_id = int(path.rsplit("/", 1)[-1])
            return httpx.Response(
                200,
                json={
                    "id": tmdb_id,
                    "title": f"Title {tmdb_id}",
                    "genres": [{"id": 18, "name": "Drama"}]
                    if tmdb_id >= 601
                    else [{"id": 35, "name": "Comedy"}],
                    "vote_count": 1000,
                    "recommendations": {"results": results(601, suggestion_media)},
                    "similar": {"results": results(701, suggestion_media)},
                    "watch/providers": {
                        "results": {"US": {"flatrate": [{"provider_id": 8}] if tmdb_id % 2 else []}}
                    },
                },
            )
        raise AssertionError(f"unexpected fixture route: {path}")

    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        fixture_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.state.http = fixture_http
        try:
            members = client.get("/api/v1/recommendations/household-members").json()
            home = client.get("/api/v1/home")
            extra = client.get("/api/v1/rails")
            title = client.get("/api/v1/title/movie/1001")
            search = client.get("/api/v1/search?q=Title")
            blend = client.post(
                "/api/v1/recommendations/household-blend",
                json={"user_ids": [member["id"] for member in members]},
            )
            assert (
                home.status_code
                == extra.status_code
                == title.status_code
                == search.status_code
                == blend.status_code
                == 200
            )
            assert blend.json() is not None
            discovery_rails = (
                [rail for rail in home.json()["rails"] if rail["id"] != "my-list"]
                + extra.json()["rails"]
                + [blend.json()]
            )
            assert discovery_rails
            assert mode == "seerr_outage" or all(
                item["id"] % 2 == 0 for rail in discovery_rails for item in rail["items"]
            )
            home_rails = {rail["id"]: rail["items"] for rail in home.json()["rails"]}
            assert {
                "my-list",
                "recommended-for-you",
                "trending",
                "popular",
                "popular-tv",
                "recently-added",
            } <= home_rails.keys()
            for rail_id, start in (
                ("trending", 1),
                ("popular", 101),
                ("popular-tv", 201),
                ("recently-added", 301),
            ):
                assert [item["id"] for item in home_rails[rail_id]] == expected_ids(start)
            assert home.json()["hero"]
            assert [slide["item"]["id"] for slide in home.json()["hero"]] == expected_ids(1)[:5]
            extra_rails = {rail["id"]: rail["items"] for rail in extra.json()["rails"]}
            assert {
                "top-rated-movie",
                "top-rated-tv",
                "decade-2020",
                "decade-2010",
            } == extra_rails.keys()
            assert [item["id"] for item in extra_rails["top-rated-movie"]] == expected_ids(401)
            assert [item["id"] for item in extra_rails["top-rated-tv"]] == expected_ids(501)
            assert all(rail["items"] for rail in discovery_rails)
            assert (
                next(rail for rail in home.json()["rails"] if rail["id"] == "my-list")["items"][0][
                    "id"
                ]
                == 1001
            )
            assert title.json()["id"] == 1001
            assert [item["id"] for item in title.json()["recommendations"]] == expected_ids(601)
            assert [item["id"] for item in title.json()["similar"]] == expected_ids(701)
            assert [item["id"] for item in search.json()["results"]] == list(range(1, 21))
            if environment and not library:
                asyncio.run(persist("GB"))
                changed = client.get("/api/v1/title/movie/1001")
                assert changed.status_code == 200
                assert [item["id"] for item in changed.json()["recommendations"]] == list(
                    range(601, 621)
                )
        finally:
            asyncio.run(fixture_http.aclose())


@pytest.mark.parametrize(
    "rail_type", [RailType.RECOMMENDED, RailType.MORE_LIKE, RailType.UNEXPECTED_PICKS]
)
@pytest.mark.parametrize("mode", ["empty", "failed", "no_signals", "ordinary_failed"])
def test_personalized_only_home_classifies_actual_candidate_sources(
    tmp_path: Path,
    rail_type: RailType,
    mode: str,
) -> None:
    from tasterr.recommend.store import save_profile

    db_path = tmp_path / "tasterr.db"
    app = create_app(
        Settings.model_validate(
            {
                "database_path": db_path,
                "static_dir": tmp_path / "static",
                "tasterr_secret_key": SECRET,
                "tmdb_api_key": "fixture-key",
            }
        )
    )
    token = _seed_session(db_path)
    if mode != "no_signals":
        _record_signals(db_path, ["request"], tmdb_id=1001)

    async def seed() -> None:
        engine = create_engine(db_path)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                await save_runtime_settings(
                    db,
                    RuntimeSettings(
                        excluded_service_ids=[8],
                        disabled_rail_types=[
                            rail
                            for rail in RailType
                            if rail != rail_type
                            and not (
                                mode == "ordinary_failed"
                                and rail in (RailType.TRENDING, RailType.POPULAR, RailType.RECENT)
                            )
                        ],
                    ),
                )
                if mode != "no_signals" and not (
                    mode == "ordinary_failed" and rail_type == RailType.UNEXPECTED_PICKS
                ):
                    await save_profile(db, 1, {"genre:drama": 1.0})
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(seed())
    source_calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/genre/" in path:
            return httpx.Response(200, json={"genres": [{"id": 18, "name": "Drama"}]})
        source_calls.append(path)
        if mode == "failed":
            return httpx.Response(404, json={})
        if "/movie/" in path:
            return httpx.Response(
                200,
                json={
                    "id": 1001,
                    "title": "Source",
                    "genres": [{"id": 18, "name": "Drama"}],
                    "recommendations": {"results": []},
                    "similar": {"results": []},
                },
            )
        if "/discover/" in path or "/trending/" in path:
            if mode == "ordinary_failed":
                return httpx.Response(404, json={})
            return httpx.Response(200, json={"results": [], "total_pages": 1})
        raise AssertionError(f"unexpected fixture route: {path}")

    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        fixture_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.state.http = fixture_http
        try:
            response = client.get("/api/v1/home")
            succeeds = mode == "empty" or (
                mode == "ordinary_failed" and rail_type != RailType.UNEXPECTED_PICKS
            )
            assert response.status_code == (200 if succeeds else 502)
            if succeeds:
                assert response.json() == {"hero": [], "rails": []}
                assert source_calls
                count = len(source_calls)
                assert client.get("/api/v1/home").status_code == 200
                if mode == "empty":
                    assert len(source_calls) == count
                else:
                    assert source_calls.count("/3/movie/1001") == 1
                    assert any("/discover/" in path for path in source_calls)
                    assert any("/trending/" in path for path in source_calls)
            elif mode == "no_signals":
                assert source_calls == []
            elif mode == "ordinary_failed":
                assert "/3/movie/1001" in source_calls
                assert any("/discover/" in path for path in source_calls)
                assert any("/trending/" in path for path in source_calls)
        finally:
            asyncio.run(fixture_http.aclose())


@pytest.mark.parametrize("stage", ["detail", "suggestions", "cancelled"])
async def test_title_drains_parallel_availability_on_every_error(
    monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    from sqlalchemy.ext.asyncio import AsyncSession

    from tasterr.recommend import store

    started = asyncio.Event()
    checking = asyncio.Event()
    cancelled = asyncio.Event()

    class StalledAvailability:
        async def status(self, media: str, tmdb_id: int) -> Never:
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    class BrokenCatalog(FakeCatalog):
        async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
            await started.wait()
            if stage == "detail":
                raise UpstreamUnavailable("catalog unavailable")
            return _detail(tmdb_id).model_copy(update={"recommendations": [_summary(2)]})

        async def title_facts(self, media: str, tmdb_id: int) -> Never:
            checking.set()
            if stage == "cancelled":
                await asyncio.Event().wait()
            raise ValueError("invalid internal facts")

    async def toggles(
        db: AsyncSession, user_id: int, media: str, tmdb_id: int
    ) -> tuple[bool, bool]:
        return False, False

    monkeypatch.setattr(store, "title_toggles", toggles)
    catalog = cast("CatalogService", BrokenCatalog())
    catalog.discovery_filter = DiscoveryFilter(catalog, None, False, [8])
    task = asyncio.create_task(
        get_title(
            "movie",
            1,
            catalog,
            cast("AvailabilityService", StalledAvailability()),
            AuthedSession(user=User(id=1), session=UserSession()),
            cast("AsyncSession", object()),
        )
    )
    async with asyncio.timeout(0.5):
        if stage == "cancelled":
            await checking.wait()
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            with pytest.raises(UpstreamUnavailable if stage == "detail" else ExceptionGroup):
                await task
    assert cancelled.is_set()
    assert task.done()


def _app(tmp_path: Path, *, tmdb: bool = True, plex_max_connection_probes: int = 6) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": SECRET,
        "seerr_internal_url": "http://seerr:5055",
        "seerr_api_key": "seerr-api-key",
        "tasterr_plex_max_connection_probes": plex_max_connection_probes,
    }
    if tmdb:
        overrides["tmdb_api_key"] = "tmdb-key"
    app = create_app(Settings.model_validate(overrides))
    # Default browse tests exercise the catalog, not Seerr — give them a no-client
    # availability service so title detail never makes a live Seerr call. Tests that
    # assert availability re-override get_availability with a mock-backed client.
    app.dependency_overrides[get_availability] = lambda: AvailabilityService(None, Cache())
    return app


def _seed_session(db_path: Path, *, plex: bool = False) -> str:
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
                    auth_type="plex" if plex else "local",
                    is_admin=False,
                )
                db.add(user)
                await db.flush()
                plex_token = encrypt_token(SECRET, "plex-token") if plex else None
                return await mint_session(db, user.id, "connect.sid=s%3Aseed", plex_token)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _authed_client(app: FastAPI, db_path: Path) -> TestClient:
    token = _seed_session(db_path)
    client = TestClient(app)
    client.cookies.set("tasterr_session", token)
    return client


def test_plex_backed_home_evaluates_history_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    captured: list[tuple[int, bool]] = []

    def recorder(
        request: object,
        settings: object,
        user_id: int,
        attempted_at: object,
        plex_token_enc: str | None,
    ) -> None:
        captured.append((user_id, plex_token_enc is not None))

    monkeypatch.setattr("tasterr.api.home.schedule_plex_history", recorder)

    def unreadable(_secret_key: str, _ciphertext: str) -> Never:
        raise InvalidToken

    monkeypatch.setattr("tasterr.api.home.decrypt_token", unreadable)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex=True)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.get("/api/v1/home")

    assert response.status_code == 200
    assert captured == [(1, True)]


def test_home_passes_configured_plex_connection_probe_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, plex_max_connection_probes=8)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    captured: list[int] = []

    class RecordingPlexClient:
        def __init__(
            self,
            _http: object,
            _client_identifier: str,
            *,
            max_connection_probes: int,
        ) -> None:
            captured.append(max_connection_probes)

        async def account(self, _account_token: str) -> PlexCloudAccount:
            return PlexCloudAccount(id=1, username="member")

        async def discover_servers(self, _account_token: str) -> PlexServerDiscovery:
            return PlexServerDiscovery((), complete=True)

    monkeypatch.setattr("tasterr.api.home.PlexMediaClient", RecordingPlexClient)

    def ignore_schedule(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.home.schedule_plex_history", ignore_schedule)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex=True)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.get("/api/v1/home")

    assert response.status_code == 200
    assert captured == [8]


def test_disabled_continue_watching_does_not_decrypt_account_token(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    app.dependency_overrides[get_runtime_settings] = lambda: RuntimeSettings(
        disabled_rail_types=[RailType.CONTINUE_WATCHING]
    )

    def ignore_schedule(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.home.schedule_plex_history", ignore_schedule)

    def unexpected_decrypt(_secret_key: str, _ciphertext: str) -> Never:
        raise AssertionError("disabled Continue Watching decrypted its token")

    monkeypatch.setattr("tasterr.api.home.decrypt_token", unexpected_decrypt)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex=True)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.get("/api/v1/home")

    assert response.status_code == 200


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
        deep = client.get("/api/v1/rails?cursor=12").json()

    assert first["next_cursor"] == 4
    assert deep["next_cursor"] is None  # catalogue exhausted


def test_rails_pass_the_signed_in_user_to_daily_ordering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: list[int | None] = []

    async def capture(ctx: RailContext, _cursor: int) -> RailsPage:
        captured.append(ctx.user.id if ctx.user is not None else None)
        return RailsPage()

    monkeypatch.setattr("tasterr.api.home.build_extra_rails", capture)
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/rails")

    assert response.status_code == 200
    assert captured == [1]


# ── Title detail (4.2) ───────────────────────────────────────────────────────


def test_title_detail_returns_media_detail(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/42")

    assert response.status_code == 200
    assert response.json()["id"] == 42
    assert response.json()["external_url"] == "https://www.themoviedb.org/movie/42"


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
    _override_availability(
        app,
        lambda _: httpx.Response(
            200,
            json={
                "mediaInfo": {
                    "status": 5,
                    "plexUrl": "https://app.plex.tv/desktop/#!/details",
                    "iOSPlexUrl": "plex://preplay/?metadataKey=x",
                }
            },
        ),
    )
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        response = client.get("/api/v1/title/movie/42")

    assert response.status_code == 200
    availability = response.json()["availability"]
    assert availability["status"] == "available"
    assert availability["known"] is True
    assert availability["playback"]["regular"]["web_url"] == (
        "https://app.plex.tv/desktop/#!/details"
    )
    assert availability["playback"]["regular"]["android_intent_url"].startswith("intent://preplay/")


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
    assert body["availability"] == {
        "status": "unknown",
        "known": False,
        "regular_status": "unknown",
        "four_k_status": "unknown",
        "playback": None,
    }


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


# ── Per-user taste flags on detail (M4) ──────────────────────────────────────


def _record_signals(
    db_path: Path, kinds: list[SignalKind], *, seerr_user_id: int = 99, tmdb_id: int = 42
) -> None:
    """Write signals for the user keyed by Seerr id (created if absent)."""

    async def _run() -> None:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = (
                    await db.execute(select(User).where(User.seerr_user_id == seerr_user_id))
                ).scalar_one_or_none()
                if user is None:
                    user = User(
                        seerr_user_id=seerr_user_id, display_name="other", auth_type="local"
                    )
                    db.add(user)
                    await db.flush()
                for kind in kinds:
                    await record_signal(db, user.id, "movie", tmdb_id, kind)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def test_detail_flags_reflect_the_callers_signals(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        _record_signals(db_path, ["watchlist", "not_interested"])
        response = client.get("/api/v1/title/movie/42")

    assert response.status_code == 200
    assert response.json()["taste"] == {"watchlisted": True, "hidden": True}


def test_detail_flags_are_neutral_without_signals(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    with _authed_client(app, tmp_path / "tasterr.db") as client:
        response = client.get("/api/v1/title/movie/42")

    assert response.json()["taste"] == {"watchlisted": False, "hidden": False}


def test_detail_flags_never_leak_another_users_signals(tmp_path: Path) -> None:
    app = _app(tmp_path)
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", FakeCatalog())
    db_path = tmp_path / "tasterr.db"
    with _authed_client(app, db_path) as client:
        _record_signals(db_path, ["watchlist"], seerr_user_id=7)  # somebody else's list
        response = client.get("/api/v1/title/movie/42")

    assert response.json()["taste"] == {"watchlisted": False, "hidden": False}


# ── Personalized home through the real API path (M4 milestone bar) ───────────
#
# These go through real sessions, the real store/profile/scorer, and the real
# composer — the layer where a shared-AsyncSession concurrency bug silently
# dropped the personalized rails before the providers were serialized.


class TasteCatalog(FakeCatalog):
    """FakeCatalog plus the surfaces the taste engine consumes."""

    def __init__(self) -> None:
        super().__init__()
        self.recs: dict[int, list[MediaSummary]] = {}
        self.genres: dict[int, list[str]] = {}

    async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
        base = await super().detail(media, tmdb_id)
        return base.model_copy(update={"recommendations": self.recs.get(tmdb_id, [])})

    async def title_facts(self, media: str, tmdb_id: int) -> TitleFacts:
        return TitleFacts(
            tmdb_id=tmdb_id,
            media_type="tv" if media == "tv" else "movie",
            title=f"T{tmdb_id}",
            genres=self.genres.get(tmdb_id, ["Drama"]),
            vote_average=7.0,
            vote_count=1000,
        )


def _mint_session_for(db_path: Path, seerr_user_id: int) -> str:
    async def _run() -> str:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = (
                    await db.execute(select(User).where(User.seerr_user_id == seerr_user_id))
                ).scalar_one_or_none()
                if user is None:
                    user = User(
                        seerr_user_id=seerr_user_id,
                        display_name=f"member-{seerr_user_id}",
                        auth_type="local",
                    )
                    db.add(user)
                    await db.flush()
                return await mint_session(db, user.id, "connect.sid=s%3Aseed", None)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _recommended_ids(feed: dict[str, object]) -> set[int]:
    rails = cast("list[dict[str, object]]", feed["rails"])
    rail = next((r for r in rails if r["id"] == "recommended-for-you"), None)
    assert rail is not None, f"no recommended-for-you rail in {[r['id'] for r in rails]}"
    items = cast("list[dict[str, object]]", rail["items"])
    return {cast("int", item["id"]) for item in items}


def test_two_users_get_visibly_different_homes(tmp_path: Path) -> None:
    """The M4 milestone bar, end to end: two authenticated users with
    different histories receive different personalized home rails."""
    app = _app(tmp_path)
    catalog = TasteCatalog()
    catalog.recs[1001] = [_summary(1002), _summary(1003)]
    catalog.recs[1010] = [_summary(1020), _summary(1030)]
    catalog.genres.update(
        {
            1001: ["Drama"],
            1002: ["Drama"],
            1003: ["Drama"],
            1010: ["Comedy"],
            1020: ["Comedy"],
            1030: ["Comedy"],
        }
    )
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", catalog)
    db_path = tmp_path / "tasterr.db"
    token_a = _seed_session(db_path)  # seerr user 99
    token_b = _mint_session_for(db_path, seerr_user_id=7)
    _record_signals(db_path, ["request"], seerr_user_id=99, tmdb_id=1001)
    _record_signals(db_path, ["request"], seerr_user_id=7, tmdb_id=1010)

    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token_a)
        home_a = client.get("/api/v1/home")
        client.cookies.set("tasterr_session", token_b)
        home_b = client.get("/api/v1/home")

    assert home_a.status_code == 200
    assert home_b.status_code == 200
    ids_a = _recommended_ids(home_a.json())
    ids_b = _recommended_ids(home_b.json())
    assert {1002, 1003} <= ids_a  # recs of the title user A requested
    assert {1020, 1030} <= ids_b  # recs of the title user B requested
    assert ids_a != ids_b


def test_home_degrades_when_engine_storage_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine storage failure mid-personalization must degrade to the
    plain feed — never poison the session into a 500 at the final commit."""

    async def boom(*_args: object, **_kwargs: object) -> None:
        raise OperationalError("insert into profiles", None, Exception("disk full"))

    monkeypatch.setattr("tasterr.recommend.store.save_profile", boom)
    app = _app(tmp_path)
    catalog = TasteCatalog()
    catalog.recs[1001] = [_summary(1002), _summary(1003)]
    app.dependency_overrides[get_catalog] = lambda: cast("CatalogService", catalog)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path)
    _record_signals(db_path, ["request"], tmdb_id=1001)  # forces a profile recompute

    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.get("/api/v1/home")

    assert response.status_code == 200
    rail_ids = {rail["id"] for rail in response.json()["rails"]}
    assert "trending" in rail_ids
    assert rail_ids.isdisjoint({"my-list", "recommended-for-you", "more-like"})

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from datetime import datetime
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.factories import mint_linked_session, user_with_links
from tests.test_browse_api import (
    _app,  # pyright: ignore[reportPrivateUsage]
    _seed_session,  # pyright: ignore[reportPrivateUsage]
    _summary,  # pyright: ignore[reportPrivateUsage]
)

from tasterr.api.runtime_settings import get_runtime_settings
from tasterr.catalog.models import MediaSummary, MediaType
from tasterr.catalog.resume import ResumeCandidate
from tasterr.catalog.service import CatalogService
from tasterr.db.engine import create_engine
from tasterr.db.models import Signal
from tasterr.recommend import store
from tasterr.recommend.signals import SignalKind
from tasterr.runtime_settings import RailType, RuntimeSettings


@pytest.mark.parametrize(
    "media,kind,hide_watched",
    [
        ("movie", "watched_plex", True),
        ("tv", "watched_jellyfin", True),
        ("movie", "not_interested", False),
    ],
)
def test_personal_exclusions_cover_discovery_and_preserve_access_and_taste(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    media: MediaType,
    kind: SignalKind,
    hide_watched: bool,
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex=True)
    hidden_ids = {1, 101, 201, 301, 401, 501, 601, 701}
    runtime = RuntimeSettings(
        hide_watched_items=hide_watched,
        disabled_rail_types=[RailType.RECOMMENDED, RailType.UNEXPECTED_PICKS],
    )
    app.dependency_overrides[get_runtime_settings] = lambda: runtime

    async def seed() -> str:
        engine = create_engine(db_path)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                other = await user_with_links(
                    db, seerr_user_id=7, display_name="Other", auth_type="local"
                )
                await db.flush()
                await store.record_signal(db, 1, media, 1, "watchlist")
                await store.record_signal(db, 1, media, 601, "watchlist")
                await store.record_signal(db, 1, media, 1001, "request")
                for tmdb_id in sorted(hidden_ids):
                    # Episode imports already collapse to one watched series row.
                    await store.record_signal(db, 1, media, tmdb_id, kind)
                await store.record_signal(db, other.id, media, 1001, "request")
                await store.save_profile(db, 1, {"genre:drama": 1.0})
                await store.save_profile(db, other.id, {"genre:drama": 1.0})
                return await mint_linked_session(db, other.id, "connect.sid=other", None)
        finally:
            await engine.dispose()

    other_token = asyncio.run(seed())

    async def snapshot() -> tuple[
        list[tuple[int, str, int, str, float, datetime]], dict[str, float]
    ]:
        engine = create_engine(db_path)
        try:
            async with async_sessionmaker(engine)() as db:
                rows = (
                    await db.execute(select(Signal).where(Signal.user_id == 1).order_by(Signal.id))
                ).scalars()
                profile = await store.load_profile(db, 1)
                assert profile is not None
                return [
                    (s.id, s.media_type, s.tmdb_id, s.kind, s.weight, s.created_at) for s in rows
                ], profile.vector
        finally:
            await engine.dispose()

    before = asyncio.run(snapshot())

    async def no_history(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.home.schedule_history", no_history)

    class Resume:
        def __init__(self, *_args: object) -> None:
            pass

        async def resume_candidates(self, account_token: str) -> list[ResumeCandidate]:
            return [ResumeCandidate(media, i, -i, (0, 0), 50) for i in range(1, 7)]

    monkeypatch.setattr("tasterr.api.home.PlexCatalogService", Resume)

    def results(start: int) -> list[dict[str, object]]:
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

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if "/genre/" in path:
            return httpx.Response(200, json={"genres": [{"id": 18, "name": "Drama"}]})
        if "/trending/" in path or "/search/" in path:
            return httpx.Response(200, json={"results": results(1)})
        if "/discover/" in path:
            start = (
                301
                if "with_genres" in request.url.params
                else 401
                if request.url.params["sort_by"] == "vote_average.desc"
                else 501
                if "primary_release_date.lte" in request.url.params
                else 201
                if request.url.params["sort_by"] == "primary_release_date.desc"
                else 101
            )
            return httpx.Response(200, json={"total_pages": 1, "results": results(start)})
        if "/movie/" in path or "/tv/" in path:
            tmdb_id = int(path.rsplit("/", 1)[-1])
            return httpx.Response(
                200,
                json={
                    "id": tmdb_id,
                    "title": f"Title {tmdb_id}",
                    "name": f"Title {tmdb_id}",
                    "backdrop_path": "/fixture.jpg",
                    "genres": [{"id": 18, "name": "Drama"}],
                    "vote_count": 1000,
                    "vote_average": 7,
                    "recommendations": {"results": results(601)},
                    "similar": {"results": results(701)},
                },
            )
        raise AssertionError(f"unexpected fixture route: {path}")

    with TestClient(app) as client:
        fixture_http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        app.state.http = fixture_http
        client.cookies.set("tasterr_session", token)
        try:
            home = client.get("/api/v1/home")
            assert home.status_code == 200
            rails = {rail["id"]: rail for rail in home.json()["rails"]}
            assert {"trending", "more-like", "continue-watching"} <= rails.keys()
            if kind != "not_interested":
                assert rails["more-like"]["title"].startswith("Because You Watched")
                assert 601 in {item["id"] for item in rails["my-list"]["items"]}
            else:
                assert rails["more-like"]["title"].startswith("More Like")
            assert 1 in {item["id"] for item in rails["continue-watching"]["items"]}
            discovery = [
                rail for key, rail in rails.items() if key not in ("my-list", "continue-watching")
            ]
            cursor = 0
            extra_ids: set[str] = set()
            while True:
                extra = client.get(f"/api/v1/rails?cursor={cursor}")
                assert extra.status_code == 200
                discovery.extend(extra.json()["rails"])
                extra_ids.update(rail["id"] for rail in extra.json()["rails"])
                cursor = extra.json()["next_cursor"]
                if cursor is None:
                    break
            assert any(key.startswith("genre-") for key in extra_ids)
            assert "top-rated-movie" in extra_ids
            assert all(item["id"] not in hidden_ids for rail in discovery for item in rail["items"])
            assert home.json()["hero"]
            assert all(slide["item"]["id"] not in hidden_ids for slide in home.json()["hero"])
            detail = client.get(f"/api/v1/title/{media}/1")
            assert detail.status_code == 200 and detail.json()["id"] == 1
            assert [item["id"] for item in detail.json()["recommendations"]] == list(
                range(602, 621)
            )
            assert [item["id"] for item in detail.json()["similar"]] == list(range(702, 721))
            search = client.get("/api/v1/search?q=Title")
            assert search.status_code == 200
            assert 1 in {item["id"] for item in search.json()["results"]}
            members = client.get("/api/v1/recommendations/household-members").json()
            blend = client.post(
                "/api/v1/recommendations/household-blend",
                json={"user_ids": [member["id"] for member in members]},
            )
            assert blend.status_code == 200 and blend.json() is not None
            assert all(item["id"] not in hidden_ids for item in blend.json()["items"])
            assert asyncio.run(snapshot()) == before
            runtime.hide_watched_items = not hide_watched
            assert client.get("/api/v1/home").status_code == 200
            assert client.get(f"/api/v1/title/{media}/1").status_code == 200
            assert asyncio.run(snapshot()) == before
            runtime.hide_watched_items = hide_watched
            client.cookies.set("tasterr_session", other_token)
            other_home = client.get("/api/v1/home")
            assert other_home.status_code == 200
            other_trending = next(r for r in other_home.json()["rails"] if r["id"] == "trending")
            assert 1 in {item["id"] for item in other_trending["items"]}
        finally:
            asyncio.run(fixture_http.aclose())


@pytest.mark.parametrize("hide_watched", [False, True])
def test_no_personal_rows_preserves_unfiltered_catalog(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hide_watched: bool
) -> None:
    checked: list[bool] = []

    class UnfilteredCatalog(CatalogService):
        async def trending(self) -> list[MediaSummary]:
            checked.append(self.discovery_filter is None)
            assert self.discovery_filter is None
            return [_summary(i) for i in range(1, 7)]

    monkeypatch.setattr("tasterr.api.catalog.CatalogService", UnfilteredCatalog)
    app = _app(tmp_path)
    app.dependency_overrides[get_runtime_settings] = lambda: RuntimeSettings(
        hide_watched_items=hide_watched,
        disabled_rail_types=[rail for rail in RailType if rail != RailType.TRENDING],
    )
    token = _seed_session(tmp_path / "tasterr.db")
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.get("/api/v1/home")
    assert response.status_code == 200
    assert checked == [True]

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportPrivateUsage=false
import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import MetaData, select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import db_call
from tests.test_browse_api import FakeCatalog, _app, _seed_session
from tests.test_catalog_jellyfin import PLAYED, item
from tests.test_clients_jellyfin import KEY, USER_ID

from tasterr.api.catalog import get_catalog
from tasterr.api.runtime_settings import get_runtime_settings
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.login import get_link
from tasterr.catalog.models import MediaDetail
from tasterr.catalog.resume import ResumeCandidate, continue_watching_key
from tasterr.catalog.service import CatalogService
from tasterr.db.engine import create_engine
from tasterr.db.models import LinkedAccount, Signal
from tasterr.runtime_settings import RailType, RuntimeSettings
from tasterr.settings import Settings, get_settings

RAW_IDS = [f"{i:032x}" for i in range(10000, 10006)]
SERIES_IDS = ["d" * 32, "e" * 32]
POSITION = 432198
RUNTIME = 1080495


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    app = _app(tmp_path)
    settings = cast(Settings, app.dependency_overrides[get_settings]())
    settings.jellyfin_internal_url = "http://jellyfin:8096"
    settings.jellyfin_api_key = SecretStr(KEY)
    token = _seed_session(tmp_path / "tasterr.db")

    async def link(db: AsyncSession) -> None:
        db.add(
            LinkedAccount(
                user_id=1, provider="jellyfin", external_id=USER_ID, display_name="Viewer"
            )
        )

    db_call(tmp_path / "tasterr.db", link)

    class Catalog(FakeCatalog):
        async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
            return (await super().detail(media, tmdb_id)).model_copy(update={"media_type": media})

    app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, Catalog())

    async def no_history(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.home.schedule_history", no_history)
    app.state.test_token = token
    return app


def resume_response(request: httpx.Request) -> httpx.Response:
    assert request.url.params["userId"] == USER_ID
    assert f'Token="{KEY}"' in request.headers["Authorization"]
    assert KEY not in str(request.url)
    if request.url.path == "/UserItems/Resume":
        rows = [
            item(
                i + 20,
                Id=RAW_IDS[i],
                RunTimeTicks=RUNTIME,
                UserData={"PlaybackPositionTicks": POSITION, "LastPlayedDate": PLAYED},
            )
            for i in range(2)
        ]
    elif request.url.path == "/Shows/NextUp":
        rows = [
            item(
                i + 30,
                Id=RAW_IDS[i + 2],
                Type="Episode",
                SeriesId=SERIES_IDS[i],
                ParentIndexNumber=2,
                IndexNumber=3 + i,
            )
            for i in range(2)
        ]
    elif request.url.path == "/Items" and "Filters" in request.url.params:
        assert request.url.params["IncludeItemTypes"] == "Episode"
        assert request.url.params["Limit"] == "100"
        assert request.url.params["EnableUserData"] == "true"
        rows = [
            item(i + 40, Id=RAW_IDS[i + 4], Type="Episode", SeriesId=SERIES_IDS[i])
            for i in range(2)
        ]
    else:
        assert request.url.path == "/Items"
        assert request.url.params["Ids"] == ",".join(SERIES_IDS)
        rows = [item(i + 30, Id=SERIES_IDS[i], Type="Series", UserData=None) for i in range(2)]
    return httpx.Response(200, json={"Items": rows, "TotalRecordCount": len(rows)})


def test_jellyfin_only_home_exposes_summaries_and_persists_no_resume_data(
    app: FastAPI,
    tmp_path: Path,
) -> None:
    async def snapshot() -> dict[str, list[dict[str, object]]]:
        engine = create_engine(tmp_path / "tasterr.db")
        try:
            async with engine.connect() as connection:
                metadata = MetaData()
                await connection.run_sync(metadata.reflect)
                tables: dict[str, list[dict[str, object]]] = {}
                for name, table in metadata.tables.items():
                    assert not any(
                        "progress" in c.name or "position" in c.name or "jellyfin_item" in c.name
                        for c in table.columns
                    )
                    rows = (await connection.execute(select(table))).mappings().all()
                    tables[name] = [dict(row) for row in rows]
                return tables
        finally:
            await engine.dispose()

    before = asyncio.run(snapshot())
    requests: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request.url.path)
        return resume_response(request)

    with TestClient(app) as client:
        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        app.state.http = http
        client.cookies.set("tasterr_session", app.state.test_token)
        try:
            response = client.get("/api/v1/home")
            assert response.status_code == 200
            rail = response.json()["rails"][0]
            assert rail["id"] == "continue-watching"
            assert [
                (c["id"], c["media_type"], c["progress_percent"], c["context"])
                for c in rail["items"]
            ] == [
                (20, "movie", 40, None),
                (21, "movie", 40, None),
                (30, "tv", None, "S2 E3"),
                (31, "tv", None, "S2 E4"),
            ]
            for forbidden in [*RAW_IDS, *SERIES_IDS, USER_ID, KEY, str(POSITION), str(RUNTIME)]:
                assert forbidden not in response.text
            assert client.get("/api/v1/home").status_code == 200
            assert sorted(requests) == ["/Items", "/Items", "/Shows/NextUp", "/UserItems/Resume"]
        finally:
            asyncio.run(http.aclose())
    after = asyncio.run(snapshot())
    assert after[Signal.__tablename__] == before[Signal.__tablename__] == []
    for name, rows in after.items():
        for forbidden in [*RAW_IDS, *SERIES_IDS, str(POSITION), str(RUNTIME)]:
            assert forbidden not in str(rows)
        if name != "sessions":
            assert rows == before[name]


@pytest.mark.parametrize("mode", ["disabled", "dormant", "unlinked", "outage"])
def test_gating_and_outage_do_no_repeat_reads(app: FastAPI, tmp_path: Path, mode: str) -> None:
    settings = cast(Settings, app.dependency_overrides[get_settings]())
    if mode == "disabled":
        app.dependency_overrides[get_runtime_settings] = lambda: RuntimeSettings(
            disabled_rail_types=[RailType.CONTINUE_WATCHING]
        )
    elif mode == "dormant":
        settings.jellyfin_api_key = None
    elif mode == "unlinked":

        async def remove(db: AsyncSession) -> None:
            link = await get_link(db, 1, "jellyfin")
            assert link is not None
            await db.delete(link)

        db_call(tmp_path / "tasterr.db", remove)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        assert mode == "outage"
        return httpx.Response(503)

    with TestClient(app) as client:
        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        app.state.http = http
        client.cookies.set("tasterr_session", app.state.test_token)
        try:
            for _ in range(2):
                response = client.get("/api/v1/home")
                assert response.status_code == 200
                assert "continue-watching" not in [r["id"] for r in response.json()["rails"]]
            assert calls == (3 if mode == "outage" else 0)
        finally:
            asyncio.run(http.aclose())


def test_unlink_jellyfin_invalidates_shared_entry_and_next_home_reads_remaining_source(
    app: FastAPI,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plex_calls = 0

    async def link(db: AsyncSession) -> None:
        db.add(
            LinkedAccount(
                user_id=1,
                provider="plex",
                external_id="1",
                display_name="Viewer",
                credential_enc=encrypt_token("test-secret-key", "account-token"),
            )
        )

    db_call(tmp_path / "tasterr.db", link)

    class Plex:
        def __init__(self, *_args: object) -> None:
            pass

        async def resume_candidates(self, token: str) -> list[ResumeCandidate]:
            nonlocal plex_calls
            plex_calls += 1
            assert token == "account-token"
            return [ResumeCandidate("movie", i, 100, (0, 0), 50) for i in (20, 40, 41, 42)]

    monkeypatch.setattr("tasterr.api.home.PlexCatalogService", Plex)
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return resume_response(request)

    with TestClient(app) as client:
        http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        app.state.http = http
        client.cookies.set("tasterr_session", app.state.test_token)
        try:
            merged = client.get("/api/v1/home").json()["rails"][0]
            assert merged["id"] == "continue-watching"
            assert len(merged["items"]) == 7
            assert merged["items"][0]["id"] == 20 and merged["items"][0]["progress_percent"] == 40
            invalidated: list[str] = []
            original = app.state.catalog_cache.invalidate

            async def invalidate(key: str) -> None:
                invalidated.append(key)
                await original(key)

            monkeypatch.setattr(app.state.catalog_cache, "invalidate", invalidate)
            assert client.post("/api/v1/account/links/jellyfin/unlink", json={}).status_code == 204
            assert invalidated == [continue_watching_key(1)]
            remaining = client.get("/api/v1/home").json()["rails"][0]
            assert remaining["id"] == "continue-watching"
            assert [c["id"] for c in remaining["items"]] == [20, 40, 41, 42]
            assert calls == 4
            assert plex_calls == 2
        finally:
            asyncio.run(http.aclose())

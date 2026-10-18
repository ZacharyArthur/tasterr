# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import asyncio
from pathlib import Path
from threading import Event
from typing import cast

import pytest
from fastapi.testclient import TestClient
from tests.test_browse_api import FakeCatalog, _app, _seed_session

from tasterr.api.catalog import get_catalog
from tasterr.catalog.service import CatalogService
from tasterr.clients.seerr import SeerrClient, SeerrHistoricalRequest
from tasterr.settings import Settings, get_settings


def test_dormant_plex_link_gets_no_home_sync_or_continue_watching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    settings = cast(Settings, app.dependency_overrides[get_settings]())
    settings.seerr_internal_url = None
    settings.seerr_api_key = None
    token = _seed_session(tmp_path / "tasterr.db", plex=True)
    app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, FakeCatalog())

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("Dormant links must not schedule history or construct a Plex client")

    monkeypatch.setattr("tasterr.api.taste.schedule_seed", unexpected)
    monkeypatch.setattr("tasterr.api.taste.schedule_plex_history", unexpected)
    monkeypatch.setattr("tasterr.api.home.PlexMediaClient", unexpected)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        assert client.get("/api/v1/home").status_code == 200
        assert app.state.seed_tasks == {} and app.state.plex_history_tasks == {}


def test_home_and_reset_share_one_throttled_seerr_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, FakeCatalog())
    started = Event()
    release: asyncio.Event | None = None
    calls = 0

    async def history(_self: SeerrClient, _id: int) -> list[SeerrHistoricalRequest]:
        nonlocal calls, release
        calls += 1
        release = asyncio.Event()
        started.set()
        await release.wait()
        return []

    monkeypatch.setattr(SeerrClient, "list_requests", history)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        assert client.post("/api/v1/recommendations/reset").status_code == 204
        assert started.wait(2)
        assert client.get("/api/v1/home").status_code == 200
        assert calls == 1
        assert client.portal is not None

        async def finish() -> None:
            assert release is not None
            task = app.state.seed_tasks[1]
            release.set()
            await task

        client.portal.call(finish)
        assert client.get("/api/v1/home").status_code == 200
        assert calls == 1 and app.state.seed_tasks == {}

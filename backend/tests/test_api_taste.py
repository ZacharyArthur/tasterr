import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.types import Scope

import tasterr.api.taste as taste_api
from tasterr.api.taste import schedule_seed
from tasterr.cache import Cache
from tasterr.catalog.service import CatalogService
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.runtime_settings import save_runtime_settings
from tasterr.recommend.service import TasteService
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings


async def test_background_seed_resolves_its_own_runtime_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        await save_runtime_settings(db, RuntimeSettings(region="GB", service_ids=[8, 337]))
        await db.commit()

    captured: list[tuple[str, tuple[int, ...]]] = []

    def fake_taste(
        db: AsyncSession,
        catalog: CatalogService,
        availability: object | None = None,
    ) -> TasteService:
        captured.append((catalog.region, catalog.selected_service_ids))
        return cast("TasteService", object())

    async def fake_seed(
        seed_maker: async_sessionmaker[AsyncSession],
        factory: Callable[[AsyncSession], TasteService],
        seerr: SeerrClient,
        seeding: set[int],
        user_id: int,
        seerr_user_id: int,
        *,
        reserved: bool = False,
    ) -> None:
        assert reserved is True
        async with seed_maker() as db:
            factory(db)

    monkeypatch.setattr(taste_api, "TasteService", fake_taste)
    monkeypatch.setattr(taste_api, "seed_in_background", fake_seed)

    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    app = FastAPI()
    app.state.http = http
    app.state.catalog_cache = Cache()
    app.state.sessionmaker = maker
    seeding: set[int] = set()
    app.state.seeding = seeding
    seed_tasks: set[asyncio.Task[None]] = set()
    app.state.seed_tasks = seed_tasks
    scope = cast(
        "Scope",
        {
            "type": "http",
            "app": app,
            "method": "POST",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "scheme": "http",
        },
    )
    request = Request(scope)
    settings = Settings.model_validate(
        {
            "tmdb_api_key": "tmdb-key",
            "seerr_internal_url": "http://seerr:5055",
            "seerr_api_key": "seerr-key",
        }
    )

    schedule_seed(request, settings, user_id=1, seerr_user_id=7)
    assert seeding == {1}
    schedule_seed(request, settings, user_id=1, seerr_user_id=7)
    tasks = list(seed_tasks)
    await asyncio.gather(*tasks)

    assert captured == [("GB", (8, 337))]
    assert seeding == set()
    await http.aclose()
    await engine.dispose()

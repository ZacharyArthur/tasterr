# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from datetime import timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from tests.test_account_api import LOCAL
from tests.test_auth_api import _harness
from tests.test_recommend_service import FakeCatalog

from tasterr.catalog.facts import TitleFacts
from tasterr.catalog.service import CatalogService
from tasterr.db.models import utcnow
from tasterr.recommend import store
from tasterr.recommend.service import TasteService
from tasterr.recommend.signals import MediaType


@pytest.mark.parametrize("action", ["switch-off", "clear", "replace", "rewatch"])
async def test_mutation_during_vector_fetch_cannot_publish_stale_profile(
    tmp_path: Path, action: str
) -> None:
    harness = _harness(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    class PausedCatalog(FakeCatalog):
        async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
            started.set()
            await release.wait()
            return await super().title_facts(media, tmdb_id)

    catalog = PausedCatalog()
    catalog.genres_by_title[("movie", 2)] = ["Comedy"]
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
        asyncio.timeout(10),
    ):
        assert (await client.post("/api/v1/auth/local", json=LOCAL)).status_code == 200
        maker = harness.app.state.sessionmaker
        async with maker() as db:
            await store.record_signal(
                db, 1, "movie", 1, "watched_plex", utcnow() - timedelta(days=90)
            )
            if action == "rewatch":
                await store.record_signal(db, 1, "movie", 2, "watchlist")
            await db.commit()

        async def build() -> None:
            async with maker() as db:
                await TasteService(db, cast(CatalogService, catalog)).recompute_profile(1)
                await db.commit()

        task = asyncio.create_task(build())
        try:
            await started.wait()
            if action == "switch-off":
                response = await client.post(
                    "/api/v1/account/taste-sources", json={"source": "plex", "enabled": False}
                )
                assert response.status_code == 204
            elif action in ("clear", "replace"):
                assert (
                    await client.post("/api/v1/account/taste-sources/plex/clear")
                ).status_code == 204
                if action == "replace":
                    assert (
                        await client.post(
                            "/api/v1/signals",
                            json={"media_type": "movie", "tmdb_id": 2, "kind": "watchlist"},
                        )
                    ).status_code == 200
            else:
                async with maker() as db:
                    await store.record_signal(db, 1, "movie", 1, "watched_plex")
                    await db.commit()
            release.set()
            await task
        finally:
            release.set()
            await asyncio.gather(task, return_exceptions=True)

        async with maker() as db:
            assert await store.load_profile(db, 1) is None
            current = await TasteService(db, cast(CatalogService, catalog)).profile_vector(1)
            if action in ("switch-off", "clear"):
                assert current == {}
            elif action == "replace":
                assert current.get("genre:comedy", 0) > 0
                assert "genre:drama" not in current
            else:
                assert current["genre:drama"] > current["genre:comedy"]

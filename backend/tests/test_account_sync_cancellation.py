# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from sqlalchemy import select
from tests.test_account_api import LOCAL
from tests.test_auth_api import PLEX_TOKEN, SECRET, _harness
from tests.test_recommend_seed import _taste

from tasterr.api.taste import import_jellyfin_history, import_plex_history
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.login import get_link
from tasterr.catalog.plex import PlexCatalogService, PlexHistoryResult
from tasterr.clients.jellyfin import JellyfinClient, JellyfinItems
from tasterr.clients.seerr import SeerrClient, SeerrHistoricalRequest
from tasterr.db.models import LinkedAccount, Profile, Provider, Signal, User
from tasterr.recommend.seed import seed_in_background


@pytest.mark.parametrize("provider", ["plex", "seerr", "jellyfin"])
@pytest.mark.parametrize("action", ["unlink", "delete", "reset"])
async def test_account_mutation_awaits_real_import_and_prevents_later_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Provider, action: str
) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    started, cancelled = asyncio.Event(), asyncio.Event()

    class HangingHistory:
        async def read(self) -> None:
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise

        async def history(
            self, _token: str, *, viewed_after: int, viewed_before: int
        ) -> PlexHistoryResult:
            await self.read()
            raise AssertionError("unreachable")

        async def list_requests(self, _user_id: int) -> list[SeerrHistoricalRequest]:
            await self.read()
            raise AssertionError("unreachable")

        async def played_items(self, _user_id: str, _kind: str, _offset: int) -> JellyfinItems:
            await self.read()
            raise AssertionError("unreachable")

    async def no_restart(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.recommendations.schedule_history", no_restart)
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
        asyncio.timeout(10),
    ):
        assert (await client.post("/api/v1/auth/local", json=LOCAL)).status_code == 200
        pin = (await client.post("/api/v1/account/links/plex/pin")).json()["pin_id"]
        assert (
            await client.post("/api/v1/account/links/plex/pin/poll", json={"pin_id": pin})
        ).status_code == 200
        state = harness.app.state
        await asyncio.gather(*state.seed_tasks.values(), *state.plex_history_tasks.values())
        maker = state.sessionmaker
        async with maker() as db:
            if provider == "jellyfin":
                db.add(
                    LinkedAccount(
                        user_id=1, provider="jellyfin", external_id="a" * 32, display_name="Viewer"
                    )
                )
                await db.flush()
            link = await get_link(db, 1, provider)
            assert link is not None
            link.sync_attempted_at = None
            await db.commit()
        if provider == "plex":
            coroutine = import_plex_history(
                maker,
                cast(PlexCatalogService, HangingHistory()),
                SECRET,
                encrypt_token(SECRET, PLEX_TOKEN),
                1,
            )
            tasks = state.plex_history_tasks
        elif provider == "seerr":
            coroutine = seed_in_background(
                maker, _taste, cast(SeerrClient, HangingHistory()), state.seeding, 1
            )
            tasks = state.seed_tasks
        else:
            coroutine = import_jellyfin_history(maker, cast(JellyfinClient, HangingHistory()), 1)
            tasks = state.jellyfin_history_tasks
        task = asyncio.create_task(coroutine)
        tasks[1] = task
        await started.wait()
        async with maker() as db:
            link = await get_link(db, 1, provider)
            assert link is not None and link.sync_attempted_at is not None
        if action == "unlink":
            response = await client.post(
                f"/api/v1/account/links/{provider}/unlink", json={"delete_history": True}
            )
        elif action == "delete":
            response = await client.post("/api/v1/account/delete", json={"confirm": "Viewer"})
        else:
            response = await client.post("/api/v1/recommendations/reset")
        assert response.status_code == 204
        assert cancelled.is_set() and task.cancelled()
        assert tasks == {} and state.seeding == set()
        async with maker() as db:
            assert (await db.scalars(select(Signal))).all() == []
            assert (await db.scalars(select(Profile))).all() == []
            link = await get_link(db, 1, provider)
            if action == "reset":
                assert link is not None
                assert link.sync_attempted_at is link.sync_synced_at is None
            else:
                assert link is None
            assert (await db.get(User, 1) is None) is (action == "delete")

# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import Request
from pydantic import SecretStr
from tests.test_account_api import LOCAL
from tests.test_auth_api import _harness

from tasterr.api.taste import schedule_history
from tasterr.auth.login import get_link
from tasterr.db.models import LinkedAccount, Provider, User, utcnow
from tasterr.recommend import store
from tasterr.settings import Settings, get_settings


@pytest.mark.parametrize("provider", ["seerr", "plex", "jellyfin"])
async def test_toggle_throttle_noop_reenable_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Provider
) -> None:
    harness = _harness(tmp_path)
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    settings.plex_server_id = "pinned"
    settings.jellyfin_internal_url = "http://jellyfin:8096"
    settings.jellyfin_api_key = SecretStr("placeholder")
    scheduled: list[Provider] = []

    def seerr(*_args: object) -> None:
        scheduled.append("seerr")

    def plex(*_args: object) -> None:
        scheduled.append("plex")

    def jellyfin(*_args: object) -> None:
        scheduled.append("jellyfin")

    monkeypatch.setattr("tasterr.api.taste.schedule_seed", seerr)
    monkeypatch.setattr("tasterr.api.taste.schedule_plex_history", plex)
    monkeypatch.setattr("tasterr.api.taste.schedule_jellyfin_history", jellyfin)
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
    ):
        assert (await client.post("/api/v1/auth/local", json=LOCAL)).status_code == 200
        maker = harness.app.state.sessionmaker
        stamp = utcnow()
        async with maker() as db:
            for name in ("plex", "jellyfin"):
                db.add(
                    LinkedAccount(user_id=1, provider=name, external_id=name, display_name="Viewer")
                )
            await db.flush()
            link = await get_link(db, 1, provider)
            assert link is not None
            link.sync_attempted_at = link.sync_synced_at = stamp
            await store.record_signal(db, 1, "movie", 1, "watchlist")
            await store.save_profile(db, 1, {"genre:drama": 1})
            await db.commit()
        scheduled.clear()
        assert (
            await client.post(
                "/api/v1/account/taste-sources", json={"source": provider, "enabled": True}
            )
        ).status_code == 204
        assert scheduled == []
        async with maker() as db:
            link = await get_link(db, 1, provider)
            assert link is not None and link.sync_synced_at == stamp
            assert await store.load_profile(db, 1) is not None
        assert (
            await client.post(
                "/api/v1/account/taste-sources", json={"source": provider, "enabled": False}
            )
        ).status_code == 204
        async with maker() as db:
            assert await store.load_profile(db, 1) is None
            assert len(await store.load_signals(db, 1)) == 1
            request = Request({"type": "http", "app": harness.app})
            await schedule_history(request, settings, db, 1)
        assert provider not in scheduled
        scheduled.clear()
        assert (await client.post("/api/v1/recommendations/reset")).status_code == 204
        assert provider not in scheduled
        async with maker() as db:
            user = await db.get(User, 1)
            assert user is not None and user.taste_excluded_sources == [provider]
            link = await get_link(db, 1, provider)
            assert link is not None
            link.sync_attempted_at = link.sync_synced_at = stamp
            await db.commit()
        scheduled.clear()
        assert (
            await client.post(
                "/api/v1/account/taste-sources", json={"source": provider, "enabled": True}
            )
        ).status_code == 204
        assert scheduled == [provider]
        async with maker() as db:
            link = await get_link(db, 1, provider)
            assert link is not None and link.sync_attempted_at is link.sync_synced_at is None
            user = await db.get(User, 1)
            assert user is not None and user.taste_excluded_sources == []


@pytest.mark.parametrize("provider", ["seerr", "plex", "jellyfin"])
@pytest.mark.parametrize("action", ["switch-off", "clear"])
async def test_switch_off_holds_scheduling_guard_until_commit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Provider, action: str
) -> None:
    harness = _harness(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def cancel(request: Request, user_id: int, source: str) -> None:
        assert source == provider
        entered.set()
        await release.wait()

    monkeypatch.setattr("tasterr.api.account.cancel_source_history", cancel)
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
        asyncio.timeout(10),
    ):
        await client.post("/api/v1/auth/local", json=LOCAL)
        task = asyncio.create_task(
            client.post(
                "/api/v1/account/taste-sources"
                if action == "switch-off"
                else f"/api/v1/account/taste-sources/{provider}/clear",
                json={"source": provider, "enabled": False} if action == "switch-off" else None,
            )
        )
        await entered.wait()
        assert 1 in harness.app.state.plex_history_resets
        settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
        async with harness.app.state.sessionmaker() as db:
            await schedule_history(Request({"type": "http", "app": harness.app}), settings, db, 1)
        assert harness.app.state.seed_tasks == {}
        release.set()
        assert (await task).status_code == 204
        assert 1 not in harness.app.state.plex_history_resets

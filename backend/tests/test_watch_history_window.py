# pyright: reportPrivateUsage=false
import asyncio
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.test_plex_history_sync import _request

from tasterr.api.taste import schedule_history
from tasterr.auth.cookies import COOKIE_NAME
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.login import get_link
from tasterr.auth.sessions import mint_session
from tasterr.catalog.plex import PlexCatalogService, PlexHistoryResult
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.db.models import LinkedAccount, User
from tasterr.main import create_app
from tasterr.recommend.jellyfin_history import JellyfinHistoryResult
from tasterr.settings import Settings


@pytest.mark.parametrize("provider", ["plex", "jellyfin"])
async def test_configured_window_survives_incremental_sync_and_reset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Literal["plex", "jellyfin"]
) -> None:
    monkeypatch.setenv("TASTERR_WATCH_HISTORY_DAYS", "730")
    settings = Settings(
        database_path=tmp_path / "history.db",
        static_dir=tmp_path / "static",
        tasterr_secret_key=SecretStr("test-secret-key"),
        plex_server_id="pinned",
        jellyfin_internal_url="http://jellyfin",
        jellyfin_api_key=SecretStr("key"),
    )
    app = create_app(settings)
    request = _request()
    request.scope["app"] = app
    cutoff = datetime(2026, 10, 18, 12)
    windows: list[tuple[datetime, datetime]] = []
    monkeypatch.setattr("tasterr.api.taste.utcnow", lambda: cutoff)

    async def plex_history(
        _history: PlexCatalogService, token: str, *, viewed_after: int, viewed_before: int
    ) -> PlexHistoryResult:
        assert token == "account-token"
        windows.append(
            (
                datetime.fromtimestamp(viewed_after, UTC).replace(tzinfo=None),
                datetime.fromtimestamp(viewed_before, UTC).replace(tzinfo=None),
            )
        )
        return PlexHistoryResult((), complete=True)

    async def jellyfin_history(
        _client: JellyfinClient, external_id: str, start: datetime, end: datetime
    ) -> JellyfinHistoryResult:
        assert external_id == "a" * 32
        windows.append((start, end))
        return JellyfinHistoryResult({}, True)

    monkeypatch.setattr(PlexCatalogService, "history", plex_history)
    monkeypatch.setattr("tasterr.api.taste.read_history", jellyfin_history)
    async with app.router.lifespan_context(app), asyncio.timeout(10):
        maker = cast("async_sessionmaker[AsyncSession]", app.state.sessionmaker)
        tasks = cast(
            "dict[int, asyncio.Task[None]]",
            app.state.plex_history_tasks
            if provider == "plex"
            else app.state.jellyfin_history_tasks,
        )
        async with maker() as db:
            user = User(display_name="Viewer")
            db.add(user)
            await db.flush()
            user_id = user.id
            db.add(
                LinkedAccount(
                    user_id=user_id,
                    provider=provider,
                    external_id="a" * 32,
                    display_name="Viewer",
                    credential_enc=(
                        encrypt_token("test-secret-key", "account-token")
                        if provider == "plex"
                        else None
                    ),
                )
            )
            token = await mint_session(db, user_id)
            await db.commit()
            await schedule_history(request, settings, db, user_id)
        await asyncio.gather(*tasks.values())
        assert windows == [(cutoff - timedelta(days=730), cutoff)]

        previous = cutoff
        cutoff += timedelta(days=2)
        async with maker() as db:
            await schedule_history(request, settings, db, user_id)
        await asyncio.gather(*tasks.values())
        assert windows[-1] == (previous - timedelta(hours=24), cutoff)

        cutoff += timedelta(days=1)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://testserver",
            cookies={COOKIE_NAME: token},
        ) as client:
            response = await client.post("/api/v1/recommendations/reset")
        assert response.status_code == 204
        await asyncio.gather(*tasks.values())
        assert len(windows) == 3
        assert windows[-1] == (cutoff - timedelta(days=730), cutoff)
        async with maker() as db:
            link = await get_link(db, user_id, provider)
            assert link is not None and link.sync_synced_at == cutoff

# pyright: reportPrivateUsage=false
import asyncio
import sqlite3
from collections.abc import Iterable
from contextlib import suppress
from pathlib import Path
from typing import cast

import aiosqlite
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_recommend_seed import FakeSeerrHistory, _taste

from tasterr.api.taste import import_plex_history
from tasterr.auth.crypto import encrypt_token
from tasterr.catalog.plex import PlexCatalogService, PlexHistoryResult, PlexWatch
from tasterr.clients.seerr import SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import LinkedAccount, Provider, Signal, User, utcnow
from tasterr.recommend.seed import seed_in_background


@pytest.mark.parametrize("provider", ["plex", "seerr"])
@pytest.mark.parametrize("phase", ["initial_read", "signal_write"])
async def test_cancel_during_database_io_releases_cursor_before_returning(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, provider: Provider, phase: str
) -> None:
    engine = create_engine(tmp_path / "cancel.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(display_name="member")
        db.add(user)
        await db.flush()
        db.add(
            LinkedAccount(
                user_id=user.id, provider=provider, external_id="7", display_name="member"
            )
        )
        await db.commit()
        user_id = user.id
    started = asyncio.Event()
    release = asyncio.Event()
    cursors: list[aiosqlite.Cursor] = []
    original = aiosqlite.Cursor.fetchall

    async def pause_fetch(cursor: aiosqlite.Cursor) -> Iterable[sqlite3.Row]:
        if (
            phase == "initial_read"
            and not cursors
            and cursor.description
            and cursor.description[0][0] == "id"
        ):
            cursors.append(cursor)  # Retain the reader so garbage collection cannot hide the leak.
            started.set()
            await release.wait()
        return await original(cursor)

    monkeypatch.setattr(aiosqlite.Cursor, "fetchall", pause_fetch)
    execute = aiosqlite.Cursor.execute

    async def pause_write(
        cursor: aiosqlite.Cursor, sql: str, parameters: Iterable[object] | None = None
    ) -> aiosqlite.Cursor:
        result = await execute(cursor, sql, parameters)
        if phase == "signal_write" and not cursors and sql.startswith("INSERT INTO signals"):
            cursors.append(cursor)
            started.set()
            await release.wait()
        return result

    monkeypatch.setattr(aiosqlite.Cursor, "execute", pause_write)

    class History:
        async def history(
            self, _token: str, *, viewed_after: int, viewed_before: int
        ) -> PlexHistoryResult:
            return PlexHistoryResult((PlexWatch("movie", 42, utcnow()),), complete=True)

    seeding: set[int] = set()
    if provider == "plex":
        coroutine = import_plex_history(
            maker,
            cast(PlexCatalogService, History()),
            "secret",
            encrypt_token("secret", "token"),
            user_id,
        )
    else:
        coroutine = seed_in_background(
            maker, _taste, cast(SeerrClient, FakeSeerrHistory()), seeding, user_id
        )
    task = asyncio.create_task(coroutine)
    try:
        async with asyncio.timeout(5):
            await started.wait()
            task.cancel()
            await asyncio.sleep(0)
            task.cancel()
            await asyncio.sleep(0)
            release.set()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert cursors
            async with maker() as writer:
                assert (await writer.scalars(select(Signal))).all() == []
                link = (await writer.scalars(select(LinkedAccount))).one()
                await writer.delete(link)
                await writer.commit()
            assert seeding == set()
    finally:
        task.cancel()
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        for cursor in cursors:
            with suppress(ValueError):
                await cursor.close()
        await engine.dispose()

# pyright: reportPrivateUsage=false
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_recommend_seed import FakeSeerrHistory, _add_user, _taste

from tasterr.auth.login import get_link
from tasterr.clients.seerr import SeerrClient, SeerrHistoricalRequest
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import utcnow
from tasterr.recommend import store
from tasterr.recommend.seed import seed_in_background


async def test_incremental_overlap_skip_throttle_and_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine = create_engine(tmp_path / "seerr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    user_id = await _add_user(engine)
    now = utcnow()
    history = [
        SeerrHistoricalRequest("movie", 1, now - timedelta(hours=1)),
        SeerrHistoricalRequest("movie", 2, now - timedelta(days=3)),
        SeerrHistoricalRequest("movie", 3, now - timedelta(hours=2)),
    ]
    calls = 0
    fail = False

    async def requests(_self: FakeSeerrHistory, _id: int) -> list[SeerrHistoricalRequest]:
        nonlocal calls
        calls += 1
        async with maker() as observer:
            link = await get_link(observer, user_id, "seerr")
            assert link is not None and link.sync_attempted_at is not None
        if fail:
            raise RuntimeError("upstream failure")
        return history

    monkeypatch.setattr(FakeSeerrHistory, "list_requests", requests)
    seerr = cast(SeerrClient, FakeSeerrHistory())

    async def sync() -> None:
        await seed_in_background(maker, _taste, seerr, set(), user_id)

    try:
        async with maker() as db:
            await store.record_signal(db, user_id, "movie", 3, "request")
            await db.commit()
        await sync()
        async with maker() as db:
            signals = await store.load_signals(db, user_id)
            assert {(s.tmdb_id, s.kind) for s in signals} == {
                (1, "seed_request_history"),
                (2, "seed_request_history"),
                (3, "request"),
            }
            link = await get_link(db, user_id, "seerr")
            assert link is not None
            watermark = link.sync_synced_at
            assert watermark is not None
        await sync()
        assert calls == 1

        async def eligible() -> None:
            async with maker() as db:
                link = await get_link(db, user_id, "seerr")
                assert link is not None
                link.sync_attempted_at = now - timedelta(hours=7)
                await db.commit()

        await eligible()
        history.append(SeerrHistoricalRequest("tv", 4, now))
        history.append(SeerrHistoricalRequest("tv", 5, now - timedelta(days=3)))
        fail = True
        await sync()
        async with maker() as db:
            link = await get_link(db, user_id, "seerr")
            assert link is not None
            assert link.sync_synced_at == watermark
        await eligible()
        fail = False
        await sync()
        async with maker() as db:
            signals = await store.load_signals(db, user_id)
            assert len(signals) == 4
            assert {s.tmdb_id for s in signals} == {1, 2, 3, 4}
            link = await get_link(db, user_id, "seerr")
            assert (
                link is not None
                and link.sync_synced_at is not None
                and link.sync_synced_at >= watermark
            )
    finally:
        await engine.dispose()

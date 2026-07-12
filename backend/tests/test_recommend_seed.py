"""Cold-start seed: backdated import, single-flight, failure swallow."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import datetime
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from tasterr.catalog.facts import TitleFacts
from tasterr.catalog.models import MediaType
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.seerr import SeerrClient, SeerrHistoricalRequest
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.recommend import store
from tasterr.recommend.seed import seed_in_background, seed_user
from tasterr.recommend.service import TasteService

HISTORY = [
    SeerrHistoricalRequest("movie", 550, datetime(2025, 11, 1, 12, 0, 0)),
    SeerrHistoricalRequest("tv", 1399, datetime(2024, 6, 15, 9, 30, 0)),
]


class FakeCatalog:
    async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
        return TitleFacts(
            tmdb_id=tmdb_id,
            media_type=media,
            title=f"title-{tmdb_id}",
            genres=["Drama"],
            vote_average=7.0,
            vote_count=1000,
        )


class FakeSeerrHistory:
    def __init__(self, down: bool = False) -> None:
        self.down = down
        self.calls = 0

    async def list_requests(self, requested_by: int) -> list[SeerrHistoricalRequest]:
        self.calls += 1
        if self.down:
            raise UpstreamUnavailable("seerr down")
        assert requested_by == 7
        return HISTORY


@pytest.fixture
async def engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    yield engine
    await engine.dispose()


def _maker(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _taste(db: AsyncSession) -> TasteService:
    return TasteService(db, cast("CatalogService", FakeCatalog()))


def _seerr(fake: FakeSeerrHistory) -> SeerrClient:
    return cast("SeerrClient", fake)


async def _add_user(engine: AsyncEngine) -> int:
    async with _maker(engine)() as db:
        user = User(seerr_user_id=7, display_name="member", auth_type="plex")
        db.add(user)
        await db.commit()
        return user.id


async def test_seed_writes_backdated_signals_and_a_profile(engine: AsyncEngine) -> None:
    user_id = await _add_user(engine)
    async with _maker(engine)() as db:
        written = await seed_user(db, _taste(db), _seerr(FakeSeerrHistory()), user_id, 7)

        assert written == 2
        signals = await store.load_signals(db, user_id)
        assert [(s.media_type, s.tmdb_id, s.kind) for s in signals] == [
            ("movie", 550, "seed_request_history"),
            ("tv", 1399, "seed_request_history"),
        ]
        assert signals[0].created_at == HISTORY[0].created_at  # backdated, not "now"
        profile = await store.load_profile(db, user_id)
        assert profile is not None
        assert profile.vector.get("genre:drama", 0.0) > 0.0


async def test_seed_count_survives_a_failed_materialization(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The reset endpoint reports this count — committed signals must not be
    undercounted just because the profile rebuild (a self-healing cache) died."""

    async def boom(self: TasteService, user_id: int) -> dict[str, float]:
        raise RuntimeError("materialization on fire")

    monkeypatch.setattr(TasteService, "recompute_profile", boom)
    user_id = await _add_user(engine)
    async with _maker(engine)() as db:
        written = await seed_user(db, _taste(db), _seerr(FakeSeerrHistory()), user_id, 7)

        assert written == 2
        assert len(await store.load_signals(db, user_id)) == 2  # durable despite the failure
        assert await store.load_profile(db, user_id) is None

        # And the self-heal is real: once recompute works again, the next
        # profile read rebuilds from the durable seed signals.
        monkeypatch.undo()
        vector = await _taste(db).profile_vector(user_id)
        assert vector.get("genre:drama", 0.0) > 0.0
        assert await store.load_profile(db, user_id) is not None


async def test_reimport_is_idempotent(engine: AsyncEngine) -> None:
    """Two overlapping imports (login-seed + reset, or a double reset) cannot
    duplicate seed rows — dedupe is per user+title, not a lock."""
    user_id = await _add_user(engine)
    async with _maker(engine)() as db:
        first = await seed_user(db, _taste(db), _seerr(FakeSeerrHistory()), user_id, 7)
        second = await seed_user(db, _taste(db), _seerr(FakeSeerrHistory()), user_id, 7)

        assert (first, second) == (2, 0)
        assert len(await store.load_signals(db, user_id)) == len(HISTORY)


async def test_background_seed_skips_a_user_with_signals(engine: AsyncEngine) -> None:
    user_id = await _add_user(engine)
    fake = FakeSeerrHistory()
    maker = _maker(engine)
    async with maker() as db:
        await store.record_signal(db, user_id, "movie", 42, "detail_open")
        await db.commit()

    await seed_in_background(maker, _taste, _seerr(fake), set(), user_id, 7)

    assert fake.calls == 0  # returning user — no history read at all
    async with maker() as db:
        assert len(await store.load_signals(db, user_id)) == 1


async def test_concurrent_logins_seed_once(engine: AsyncEngine) -> None:
    user_id = await _add_user(engine)
    fake = FakeSeerrHistory()
    maker = _maker(engine)
    seeding: set[int] = set()

    await asyncio.gather(
        seed_in_background(maker, _taste, _seerr(fake), seeding, user_id, 7),
        seed_in_background(maker, _taste, _seerr(fake), seeding, user_id, 7),
    )

    assert fake.calls == 1  # single-flight: the second entry bailed
    async with maker() as db:
        assert len(await store.load_signals(db, user_id)) == len(HISTORY)
    assert seeding == set()  # always released


async def test_background_seed_swallows_seerr_failure(engine: AsyncEngine) -> None:
    user_id = await _add_user(engine)
    maker = _maker(engine)
    seeding: set[int] = set()

    await seed_in_background(
        maker, _taste, _seerr(FakeSeerrHistory(down=True)), seeding, user_id, 7
    )

    async with maker() as db:
        assert await store.has_signals(db, user_id) is False
    assert seeding == set()  # released for the next login to retry

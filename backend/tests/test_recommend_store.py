from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Signal, User, utcnow
from tasterr.recommend import store
from tasterr.recommend.features import FeatureRecord


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[AsyncSession]:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, seerr_id: int) -> int:
    user = User(seerr_user_id=seerr_id, display_name=f"member-{seerr_id}", auth_type="plex")
    db.add(user)
    await db.flush()
    return user.id


async def _all_signals(db: AsyncSession) -> list[Signal]:
    return list((await db.execute(select(Signal))).scalars().all())


async def test_toggle_add_is_idempotent(db: AsyncSession) -> None:
    user_id = await _user(db, 1)

    assert await store.record_signal(db, user_id, "movie", 550, "watchlist") is True
    assert await store.record_signal(db, user_id, "movie", 550, "watchlist") is False

    rows = await _all_signals(db)
    assert len(rows) == 1
    assert rows[0].kind == "watchlist"
    assert rows[0].weight == 2.0


async def test_retraction_removes_only_that_kind_and_title(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    await store.record_signal(db, user_id, "movie", 550, "watchlist")
    await store.record_signal(db, user_id, "movie", 550, "not_interested")
    await store.record_signal(db, user_id, "tv", 1399, "watchlist")

    await store.retract_signal(db, user_id, "movie", 550, "watchlist")

    remaining = {(s.media_type, s.tmdb_id, s.kind) for s in await _all_signals(db)}
    assert remaining == {("movie", 550, "not_interested"), ("tv", 1399, "watchlist")}


async def test_retracting_append_only_kind_raises(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    with pytest.raises(ValueError, match="append-only"):
        await store.retract_signal(db, user_id, "movie", 550, "detail_open")


async def test_detail_open_dedupes_per_day(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    yesterday = utcnow() - timedelta(days=1)

    assert await store.record_signal(db, user_id, "movie", 550, "detail_open", yesterday) is True
    assert await store.record_signal(db, user_id, "movie", 550, "detail_open") is True
    assert await store.record_signal(db, user_id, "movie", 550, "detail_open") is False

    assert len(await _all_signals(db)) == 2


async def test_reads_are_isolated_per_user(db: AsyncSession) -> None:
    alice = await _user(db, 1)
    bob = await _user(db, 2)
    await store.record_signal(db, alice, "movie", 550, "watchlist")
    await store.save_profile(db, alice, {"genre:drama": 1.0})

    assert await store.has_signals(db, bob) is False
    assert await store.load_signals(db, bob) == []
    assert await store.load_profile(db, bob) is None
    assert await store.has_signals(db, alice) is True
    assert len(await store.load_signals(db, alice)) == 1


async def test_features_round_trip_and_staleness(db: AsyncSession) -> None:
    record = FeatureRecord(vector={"genre:drama": 0.8}, vote_average=7.5, vote_count=1200)
    await store.save_features(db, ("movie", 550), record)

    fresh = await store.load_features(db, [("movie", 550)], utcnow() - timedelta(days=30))
    assert fresh == {("movie", 550): record}

    stale = await store.load_features(db, [("movie", 550)], utcnow() + timedelta(seconds=1))
    assert stale == {}


async def test_profile_round_trip_and_reset(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    await store.record_signal(db, user_id, "movie", 550, "watchlist")
    await store.save_profile(db, user_id, {"genre:drama": 1.0, "kw:heist": 0.5})

    stored = await store.load_profile(db, user_id)
    assert stored is not None
    assert stored.vector == {"genre:drama": 1.0, "kw:heist": 0.5}

    await store.delete_user_taste(db, user_id)
    assert await store.load_profile(db, user_id) is None
    assert await store.has_signals(db, user_id) is False


async def test_signal_writes_invalidate_the_materialized_profile(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    await store.save_profile(db, user_id, {"genre:stale": 1.0})

    await store.record_signal(db, user_id, "movie", 550, "watchlist")
    assert await store.load_profile(db, user_id) is None  # rebuilt on next read

    await store.save_profile(db, user_id, {"genre:stale": 1.0})
    await store.retract_signal(db, user_id, "movie", 550, "watchlist")
    assert await store.load_profile(db, user_id) is None


async def test_seed_rows_are_unique_per_title(db: AsyncSession) -> None:
    """Idempotence instead of cross-request locking: an overlapping login-seed
    and reset (or a double reset) cannot double a title's influence."""
    user_id = await _user(db, 1)

    assert await store.record_signal(db, user_id, "movie", 550, "seed_request_history") is True
    assert await store.record_signal(db, user_id, "movie", 550, "seed_request_history") is False

    assert len(await store.load_signals(db, user_id)) == 1


async def test_schema_rejects_duplicate_unique_kind_rows(db: AsyncSession) -> None:
    """The uniqueness of toggle/seed rows is a database guarantee, not an
    application check — raw inserts that bypass record_signal still cannot
    duplicate (this is what closes the cross-session TOCTOU race)."""
    user_id = await _user(db, 1)
    for _ in range(2):
        db.add(
            Signal(user_id=user_id, tmdb_id=550, media_type="movie", kind="watchlist", weight=2.0)
        )

    with pytest.raises(IntegrityError):
        await db.flush()
    await db.rollback()


async def test_append_only_kinds_are_exempt_from_the_unique_index(db: AsyncSession) -> None:
    user_id = await _user(db, 1)
    yesterday = utcnow() - timedelta(days=1)

    assert await store.record_signal(db, user_id, "movie", 550, "request") is True
    assert await store.record_signal(db, user_id, "movie", 550, "request") is True
    assert await store.record_signal(db, user_id, "movie", 550, "detail_open", yesterday) is True
    assert await store.record_signal(db, user_id, "movie", 550, "detail_open") is True

    assert len(await store.load_signals(db, user_id)) == 4


async def test_second_session_cannot_duplicate_a_seed_row(tmp_path: Path) -> None:
    """The cross-session shape of the round-2 race: a second writer (login
    seed vs. reset) hits the unique index and reports not-written."""
    engine = create_engine(tmp_path / "race.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db_a:
            user = User(seerr_user_id=1, display_name="member", auth_type="plex")
            db_a.add(user)
            await db_a.commit()
            user_id = user.id

        async with maker() as db_a, maker() as db_b:
            first = await store.record_signal(db_a, user_id, "movie", 550, "seed_request_history")
            await db_a.commit()
            second = await store.record_signal(db_b, user_id, "movie", 550, "seed_request_history")
            await db_b.commit()

            assert (first, second) == (True, False)
            assert len(await store.load_signals(db_b, user_id)) == 1
    finally:
        await engine.dispose()


async def test_reset_leaves_other_users_untouched(db: AsyncSession) -> None:
    alice = await _user(db, 1)
    bob = await _user(db, 2)
    await store.record_signal(db, alice, "movie", 550, "watchlist")
    await store.record_signal(db, bob, "movie", 550, "watchlist")
    await store.save_profile(db, bob, {"genre:drama": 1.0})

    await store.delete_user_taste(db, alice)

    assert await store.has_signals(db, bob) is True
    assert await store.load_profile(db, bob) is not None

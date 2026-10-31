import asyncio
from datetime import timedelta
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_db_migrations import _downgrade, _upgrade  # pyright: ignore[reportPrivateUsage]

from tasterr.db.engine import create_engine
from tasterr.db.models import SIGNAL_UNIQUE_INDEX_WHERE, LinkedAccount, Profile, User
from tasterr.recommend import store


async def test_populated_upgrade_concurrent_upserts_and_destructive_downgrade(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "migration.db")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade, "0009")
            await connection.execute(
                text(
                    "INSERT INTO users (id,display_name,is_admin,created_at,last_login_at,"
                    "taste_onboarding_seen) VALUES "
                    "(1,'Viewer',0,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP,0)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO profiles (user_id,vector,computed_at) "
                    "VALUES (1,'{}',CURRENT_TIMESTAMP)"
                )
            )
            await connection.commit()
            await connection.run_sync(_upgrade, "head")
            assert not (await connection.execute(text("SELECT * FROM profiles"))).all()
            index = (
                await connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE name='ux_signals_unique_per_title'")
                )
            ).scalar_one()
            assert str(SIGNAL_UNIQUE_INDEX_WHERE) in index
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = await db.get(User, 1)
            assert user is not None
            user.taste_excluded_sources = ["trakt", "browsing"]
            db.add_all(
                [
                    LinkedAccount(user_id=1, provider=p, external_id=p, display_name="Viewer")
                    for p in ("plex", "trakt")
                ]
            )
            await db.commit()

        async def write() -> None:
            async with maker() as db:
                await store.record_signal(db, 1, "movie", 1, "watched_trakt")
                await db.commit()

        await asyncio.gather(write(), write())
        async with maker() as db:
            signals = await store.load_signals(db, 1)
            assert len(signals) == 1
            original = signals[0]
            db.add(Profile(user_id=1, vector="{}"))
            await db.commit()
            assert not await store.record_signal(
                db, 1, "movie", 1, "watched_trakt", original.created_at
            )
            assert not await store.record_signal(
                db, 1, "movie", 1, "watched_trakt", original.created_at - timedelta(days=1)
            )
            assert await db.get(Profile, 1) is not None
            assert await store.record_signal(
                db, 1, "movie", 1, "watched_trakt", original.created_at + timedelta(days=1)
            )
            assert await db.get(Profile, 1) is None
            assert await store.record_signal(db, 1, "movie", 1, "watched_plex")
            await db.commit()
            assert len(await store.load_signals(db, 1)) == 2
            db.add(Profile(user_id=1, vector="{}"))
            await db.commit()
        async with engine.connect() as connection:
            await connection.run_sync(_downgrade, "0009")
            assert not (await connection.execute(text("PRAGMA foreign_key_check"))).all()
            index = (
                await connection.execute(
                    text("SELECT sql FROM sqlite_master WHERE name='ux_signals_unique_per_title'")
                )
            ).scalar_one()
            assert "watched_trakt" not in index and "watched_jellyfin" in index
        async with maker() as db:
            assert list(await db.scalars(select(User.id))) == [1]
            user = await db.get(User, 1)
            assert user is not None and user.taste_excluded_sources == ["browsing"]
            assert list(await db.scalars(select(LinkedAccount.provider))) == ["plex"]
            assert [s.kind for s in await store.load_signals(db, 1)] == ["watched_plex"]
            assert await db.get(Profile, 1) is None
    finally:
        await engine.dispose()

# pyright: reportPrivateUsage=false
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text, update
from sqlalchemy.exc import StatementError
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_db_migrations import _downgrade, _upgrade

from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Profile, Signal, User


async def test_preferences_default_validate_and_read_corruption(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "sources.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = User(display_name="member")
            db.add(user)
            await db.commit()
            assert user.taste_excluded_sources == []
            user.taste_excluded_sources = ["plex"]
            await db.commit()
            await db.refresh(user)
            assert user.taste_excluded_sources == ["plex"]
            for invalid in ("not-json", "{}", '["request"]', '["plex", 1]', "null"):
                await db.execute(
                    text("UPDATE users SET taste_excluded_sources = :value"), {"value": invalid}
                )
                await db.commit()
                await db.refresh(user)
                assert user.taste_excluded_sources == []
            with pytest.raises(StatementError, match="literal"):
                await db.execute(update(User).values(taste_excluded_sources=["invalid"]))
    finally:
        await engine.dispose()


async def test_upgrade_defaults_and_downgrade_invalidates_only_affected_profiles(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "migration.db")
    try:
        async with engine.connect() as conn:
            await conn.run_sync(_upgrade, "0008")
            await conn.execute(
                text(
                    "INSERT INTO users (id, display_name, is_admin, created_at, last_login_at) "
                    "VALUES (1, 'member', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO profiles (user_id, vector, computed_at) "
                    "VALUES (1, '{}', CURRENT_TIMESTAMP)"
                )
            )
            await conn.commit()
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = await db.get(User, 1)
            assert user is not None and user.taste_excluded_sources == []
            assert await db.get(Profile, 1) is not None
            db.add(User(id=2, display_name="other", taste_excluded_sources=["plex"]))
            await db.flush()
            db.add_all(
                [
                    Profile(user_id=2, vector="{}"),
                    Signal(user_id=2, tmdb_id=10, media_type="movie", kind="watchlist", weight=2),
                ]
            )
            await db.commit()
        async with engine.connect() as conn:
            await conn.run_sync(_downgrade, "0008")
            assert (await conn.execute(text("SELECT user_id FROM profiles"))).all() == [(1,)]
            assert (await conn.execute(text("SELECT user_id FROM signals"))).all() == [(2,)]
            assert (await conn.execute(text("PRAGMA foreign_key_check"))).all() == []
            assert (await conn.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            assert "taste_excluded_sources" not in {
                r[1] for r in (await conn.execute(text("PRAGMA table_info(users)")))
            }
        await upgrade_to_head(engine)
        async with maker() as db:
            assert list(await db.scalars(select(User.taste_excluded_sources))) == [[], []]
    finally:
        await engine.dispose()


@pytest.mark.parametrize("empty", [False, True])
async def test_downgrade_preserves_deleted_user_id_high_water(tmp_path: Path, empty: bool) -> None:
    engine = create_engine(tmp_path / "sequence.db")
    try:
        await upgrade_to_head(engine)
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            db.add_all([User(id=i, display_name="member") for i in (1, 2, 3)])
            await db.commit()
            await db.execute(delete(User).where(User.id >= (1 if empty else 3)))
            await db.commit()
        async with engine.connect() as conn:
            assert (
                await conn.execute(text("SELECT seq FROM sqlite_sequence WHERE name='users'"))
            ).scalar_one() == 3
            await conn.commit()
            await conn.run_sync(_downgrade, "0008")
            assert (
                await conn.execute(text("SELECT seq FROM sqlite_sequence WHERE name='users'"))
            ).scalar_one() == 3
            await conn.execute(
                text(
                    "INSERT INTO users (display_name, is_admin, created_at, last_login_at) "
                    "VALUES ('new', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            assert (await conn.execute(text("SELECT max(id) FROM users"))).scalar_one() == 4
            assert (await conn.execute(text("PRAGMA foreign_key_check"))).all() == []
    finally:
        await engine.dispose()

from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, delete, select, text
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from tasterr.db.engine import create_engine
from tasterr.db.migrate import ALEMBIC_DIR, upgrade_to_head
from tasterr.db.models import Profile, Setting, Signal, User


async def _stored_version(engine: AsyncEngine) -> str:
    async with engine.connect() as connection:
        result = await connection.execute(text("select version_num from alembic_version"))
        return result.scalar_one()


async def _table_names(engine: AsyncEngine) -> set[str]:
    async with engine.connect() as connection:
        result = await connection.execute(text("select name from sqlite_master where type='table'"))
        return {row[0] for row in result}


def _downgrade(connection: Connection, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["connection"] = connection
    command.downgrade(config, revision)


def _upgrade(connection: Connection, revision: str) -> None:
    config = Config()
    config.set_main_option("script_location", str(ALEMBIC_DIR))
    config.attributes["connection"] = connection
    command.upgrade(config, revision)


async def test_fresh_database_migrates_to_head(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)

        head = ScriptDirectory(str(ALEMBIC_DIR)).get_current_head()
        assert head is not None
        assert await _stored_version(engine) == head
    finally:
        await engine.dispose()


async def test_second_boot_is_a_noop(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        version_after_first = await _stored_version(engine)

        await upgrade_to_head(engine)

        assert await _stored_version(engine) == version_after_first
    finally:
        await engine.dispose()


async def test_migration_0002_creates_auth_tables(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)

        tables = await _table_names(engine)
        assert {"users", "sessions"} <= tables
    finally:
        await engine.dispose()


async def test_downgrade_drops_auth_tables(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)

        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, "0001")

        tables = await _table_names(engine)
        assert "users" not in tables
        assert "sessions" not in tables
    finally:
        await engine.dispose()


async def test_migration_0003_creates_taste_tables(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)

        tables = await _table_names(engine)
        assert {"signals", "title_features", "profiles"} <= tables
    finally:
        await engine.dispose()


async def test_downgrade_drops_taste_tables(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)

        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, "0002")

        tables = await _table_names(engine)
        assert tables.isdisjoint({"signals", "title_features", "profiles"})
        assert {"users", "sessions"} <= tables
    finally:
        await engine.dispose()


async def test_migration_0004_creates_empty_settings_table(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        assert "settings" in await _table_names(engine)

        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            assert (await db.execute(select(Setting))).scalars().all() == []
    finally:
        await engine.dispose()


async def test_downgrade_drops_only_settings_table(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = User(seerr_user_id=8, display_name="member", auth_type="local")
            db.add(user)
            db.add(Setting(key="global", value="{}"))
            await db.commit()

        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, "0003")

        tables = await _table_names(engine)
        assert "settings" not in tables
        assert {"users", "signals", "title_features", "profiles"} <= tables
        async with engine.connect() as connection:
            user_id = await connection.execute(text("select seerr_user_id from users"))
            assert user_id.scalar_one() == 8
    finally:
        await engine.dispose()


async def test_migration_0005_defaults_existing_users_to_unseen(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade, "0004")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            await db.execute(
                text(
                    "insert into users "
                    "(seerr_user_id, display_name, auth_type, is_admin, created_at, last_login_at) "
                    "values (8, 'member', 'local', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await db.commit()

        await upgrade_to_head(engine)

        async with maker() as db:
            user = (await db.execute(select(User))).scalars().one()
            assert user.taste_onboarding_seen is False
    finally:
        await engine.dispose()


async def test_downgrade_0005_preserves_users(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            db.add(User(seerr_user_id=8, display_name="member", auth_type="local"))
            await db.commit()

        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, "0004")

        async with engine.connect() as connection:
            columns = await connection.execute(text("pragma table_info(users)"))
            assert "taste_onboarding_seen" not in {row[1] for row in columns}
            count = await connection.execute(text("select count(*) from users"))
            assert count.scalar_one() == 1
    finally:
        await engine.dispose()


async def test_deleting_a_user_sweeps_taste_rows(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = User(seerr_user_id=7, display_name="member", auth_type="plex")
            db.add(user)
            await db.flush()
            db.add(
                Signal(user_id=user.id, tmdb_id=550, media_type="movie", kind="request", weight=3.0)
            )
            db.add(Profile(user_id=user.id, vector="{}"))
            await db.commit()

            await db.execute(delete(User).where(User.id == user.id))
            await db.commit()

            assert (await db.execute(select(Signal))).scalars().all() == []
            assert (await db.execute(select(Profile))).scalars().all() == []
    finally:
        await engine.dispose()

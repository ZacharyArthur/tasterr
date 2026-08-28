from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, delete, inspect, select, text
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


async def test_migration_0006_preserves_data_and_matches_user_model(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        async with engine.begin() as connection:
            await connection.run_sync(_upgrade, "0005")
            await connection.execute(
                text(
                    "insert into users "
                    "(seerr_user_id, display_name, auth_type, is_admin, taste_onboarding_seen, "
                    "created_at, last_login_at) values "
                    "(8, 'member', 'plex', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                text(
                    "insert into signals "
                    "(user_id, tmdb_id, media_type, kind, weight, created_at) "
                    "values (1, 10, 'movie', 'request', 3.0, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                text(
                    "insert into settings (key, value, updated_at) "
                    "values ('global', '{\"region\":\"GB\"}', CURRENT_TIMESTAMP)"
                )
            )

        await upgrade_to_head(engine)

        async with engine.connect() as connection:
            columns = await connection.run_sync(
                lambda sync: {column["name"] for column in inspect(sync).get_columns("users")}
            )
            user = (
                await connection.execute(
                    text(
                        "select display_name, plex_history_attempted_at, "
                        "plex_history_synced_at from users"
                    )
                )
            ).one()
            assert user == ("member", None, None)
            assert (
                await connection.execute(text("select count(*) from signals"))
            ).scalar_one() == 1
            assert (
                await connection.execute(text("select value from settings where key = 'global'"))
            ).scalar_one() == '{"region":"GB"}'
        model_columns = set(User.__table__.columns.keys())
        assert {"plex_history_attempted_at", "plex_history_synced_at"} <= columns
        assert columns == model_columns
    finally:
        await engine.dispose()


async def test_migration_0006_unique_index_includes_watched_plex(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        async with engine.connect() as connection:
            sql = (
                await connection.execute(
                    text(
                        "select sql from sqlite_master "
                        "where type = 'index' and name = 'ux_signals_unique_per_title'"
                    )
                )
            ).scalar_one()
        assert "watched_plex" in sql
    finally:
        await engine.dispose()


async def test_downgrade_0006_restores_v11_data_and_settings(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        async with engine.begin() as connection:
            await connection.execute(
                text(
                    "insert into users "
                    "(seerr_user_id, display_name, auth_type, is_admin, taste_onboarding_seen, "
                    "created_at, last_login_at) values "
                    "(8, 'member', 'plex', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                text(
                    "insert into users "
                    "(seerr_user_id, display_name, auth_type, is_admin, taste_onboarding_seen, "
                    "created_at, last_login_at) values "
                    "(9, 'other', 'local', 0, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            for kind in ("request", "watched_plex"):
                await connection.execute(
                    text(
                        "insert into signals "
                        "(user_id, tmdb_id, media_type, kind, weight, created_at) "
                        "values (1, 10, 'movie', :kind, 2.5, CURRENT_TIMESTAMP)"
                    ),
                    {"kind": kind},
                )
            await connection.execute(
                text(
                    "insert into profiles (user_id, vector, computed_at) values "
                    "(1, '{}', CURRENT_TIMESTAMP), (2, '{}', CURRENT_TIMESTAMP)"
                )
            )
            values = {
                "global": (
                    '{"region":"GB","disabled_rail_types":['
                    '"hero","continue-watching","unexpected-picks","household-blend"]}'
                ),
                "malformed": "not-json",
                "compatible": '{"disabled_rail_types":["hero"]}',
                "missing-list": '{"region":"US"}',
                "wrong-list-type": '{"disabled_rail_types":"hero"}',
            }
            for key, value in values.items():
                await connection.execute(
                    text(
                        "insert into settings (key, value, updated_at) "
                        "values (:key, :value, CURRENT_TIMESTAMP)"
                    ),
                    {"key": key, "value": value},
                )

        async with engine.begin() as connection:
            await connection.run_sync(_downgrade, "0005")

        async with engine.connect() as connection:
            columns = await connection.execute(text("pragma table_info(users)"))
            assert {"plex_history_attempted_at", "plex_history_synced_at"}.isdisjoint(
                {row[1] for row in columns}
            )
            kinds = await connection.execute(text("select kind from signals"))
            assert [row[0] for row in kinds] == ["request"]
            profiles = await connection.execute(text("select user_id from profiles"))
            assert [row[0] for row in profiles] == [2]
            settings: dict[str, str] = {
                str(row[0]): str(row[1])
                for row in (await connection.execute(text("select key, value from settings"))).all()
            }
            sql = (
                await connection.execute(
                    text(
                        "select sql from sqlite_master "
                        "where type = 'index' and name = 'ux_signals_unique_per_title'"
                    )
                )
            ).scalar_one()
        assert settings["global"] == '{"region":"GB","disabled_rail_types":["hero"]}'
        assert settings["malformed"] == "not-json"
        assert settings["compatible"] == '{"disabled_rail_types":["hero"]}'
        assert settings["missing-list"] == '{"region":"US"}'
        assert settings["wrong-list-type"] == '{"disabled_rail_types":"hero"}'
        assert "watched_plex" not in sql
        assert "seed_request_history" in sql
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

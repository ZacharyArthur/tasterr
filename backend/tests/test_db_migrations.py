from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, text
from sqlalchemy.ext.asyncio import AsyncEngine

from tasterr.db.engine import create_engine
from tasterr.db.migrate import ALEMBIC_DIR, upgrade_to_head


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

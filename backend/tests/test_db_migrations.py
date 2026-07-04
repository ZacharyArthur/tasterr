from pathlib import Path

from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from tasterr.db.engine import create_engine
from tasterr.db.migrate import ALEMBIC_DIR, upgrade_to_head


async def _stored_version(engine: AsyncEngine) -> str:
    async with engine.connect() as connection:
        result = await connection.execute(text("select version_num from alembic_version"))
        return result.scalar_one()


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

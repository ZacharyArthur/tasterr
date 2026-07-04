from pathlib import Path

from sqlalchemy import text

from tasterr.db.engine import create_engine


async def test_engine_creates_file_on_first_connect(tmp_path: Path) -> None:
    db_path = tmp_path / "nested" / "tasterr.db"

    engine = create_engine(db_path)
    try:
        async with engine.connect() as connection:
            result = await connection.execute(text("select 1"))
            assert result.scalar_one() == 1
    finally:
        await engine.dispose()

    assert db_path.exists()

from pathlib import Path

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User, UserSession, utcnow


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


def _session_row(user_id: int) -> UserSession:
    now = utcnow()
    return UserSession(
        token_hash=f"hash-{user_id}",
        user_id=user_id,
        seerr_cookie="connect.sid=s%3Ax",
        plex_token_enc=None,
        created_at=now,
        expires_at=now,
        last_seen_at=now,
    )


async def test_foreign_keys_are_enforced(tmp_path: Path) -> None:
    """SQLite ships with FK enforcement off; the engine must turn it on."""
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            db.add(_session_row(user_id=999))  # no such user
            with pytest.raises(IntegrityError):
                await db.flush()
    finally:
        await engine.dispose()


async def test_deleting_a_user_cascades_to_sessions(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "tasterr.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = User(
                seerr_user_id=1,
                display_name="Alice",
                avatar_url=None,
                auth_type="plex",
                is_admin=False,
            )
            db.add(user)
            await db.flush()
            db.add(_session_row(user_id=user.id))
            await db.commit()

            await db.delete(user)
            await db.commit()

            count = (await db.execute(select(func.count()).select_from(UserSession))).scalar_one()
            assert count == 0
    finally:
        await engine.dispose()

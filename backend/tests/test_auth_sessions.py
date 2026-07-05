# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from collections.abc import AsyncGenerator
from datetime import timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.sessions import (
    SESSION_TTL,
    hash_token,
    mint_session,
    new_token,
    resolve_session,
    revoke_session,
    sweep_expired,
)
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User, UserSession, utcnow
from tasterr.main import create_app
from tasterr.settings import Settings


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[AsyncSession]:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


async def _user(db: AsyncSession, seerr_id: int = 1) -> User:
    user = User(
        seerr_user_id=seerr_id,
        display_name="Alice",
        avatar_url=None,
        auth_type="plex",
        is_admin=False,
    )
    db.add(user)
    await db.commit()
    return user


async def _session_count(db: AsyncSession) -> int:
    return (await db.execute(select(func.count()).select_from(UserSession))).scalar_one()


async def test_mint_stores_hash_only(db: AsyncSession) -> None:
    user = await _user(db)

    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)

    row = (await db.execute(select(UserSession))).scalar_one()
    assert row.token_hash == hash_token(token)
    assert row.token_hash != token
    assert len(row.token_hash) == 64  # sha256 hex, not the raw token


async def test_resolve_round_trip(db: AsyncSession) -> None:
    user = await _user(db)
    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)

    resolved = await resolve_session(db, token)

    assert resolved is not None
    session, resolved_user = resolved
    assert resolved_user.id == user.id
    assert session.seerr_cookie == "connect.sid=s%3Aabc"


async def test_unknown_token_resolves_to_none(db: AsyncSession) -> None:
    await _user(db)

    assert await resolve_session(db, new_token()) is None


async def test_expired_session_is_rejected_and_deleted(db: AsyncSession) -> None:
    user = await _user(db)
    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)
    row = (await db.execute(select(UserSession))).scalar_one()
    row.expires_at = utcnow() - timedelta(seconds=1)
    await db.commit()

    assert await resolve_session(db, token) is None
    assert await _session_count(db) == 0


async def test_activity_slides_expiry_after_threshold(db: AsyncSession) -> None:
    user = await _user(db)
    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)
    row = (await db.execute(select(UserSession))).scalar_one()
    stale = utcnow() - timedelta(hours=2)
    row.last_seen_at = stale
    row.expires_at = utcnow() + timedelta(days=1)
    await db.commit()

    resolved = await resolve_session(db, token)

    assert resolved is not None
    session, _ = resolved
    assert session.last_seen_at > stale
    assert session.expires_at > utcnow() + SESSION_TTL - timedelta(hours=1)


async def test_slide_is_throttled_below_threshold(db: AsyncSession) -> None:
    user = await _user(db)
    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)
    row = (await db.execute(select(UserSession))).scalar_one()
    recent = utcnow() - timedelta(minutes=1)
    expires = utcnow() + timedelta(days=1)
    row.last_seen_at = recent
    row.expires_at = expires
    await db.commit()

    resolved = await resolve_session(db, token)

    assert resolved is not None
    session, _ = resolved
    assert session.last_seen_at == recent
    assert session.expires_at == expires


async def test_every_login_mints_a_fresh_token(db: AsyncSession) -> None:
    user = await _user(db)

    first = await mint_session(db, user.id, "connect.sid=s%3Aone", None)
    second = await mint_session(db, user.id, "connect.sid=s%3Atwo", None)

    assert first != second
    assert await _session_count(db) == 2


async def test_revoke_deletes_the_row(db: AsyncSession) -> None:
    user = await _user(db)
    token = await mint_session(db, user.id, "connect.sid=s%3Aabc", None)
    resolved = await resolve_session(db, token)
    assert resolved is not None

    await revoke_session(db, resolved[0])

    assert await resolve_session(db, token) is None


async def test_sweep_removes_only_expired_rows(db: AsyncSession) -> None:
    user = await _user(db)
    await mint_session(db, user.id, "connect.sid=s%3Avalid", None)
    token = await mint_session(db, user.id, "connect.sid=s%3Aexpired", None)
    row = (
        await db.execute(select(UserSession).where(UserSession.token_hash == hash_token(token)))
    ).scalar_one()
    row.expires_at = utcnow() - timedelta(days=1)
    await db.commit()

    await sweep_expired(db)

    remaining = (await db.execute(select(UserSession))).scalars().all()
    assert len(remaining) == 1
    assert remaining[0].seerr_cookie == "connect.sid=s%3Avalid"


def _seed_expired_and_valid(db_path: Path) -> None:
    async def _run() -> None:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = await _user(db)
                await mint_session(db, user.id, "connect.sid=s%3Avalid", None)
                token = await mint_session(db, user.id, "connect.sid=s%3Aexpired", None)
                row = (
                    await db.execute(
                        select(UserSession).where(UserSession.token_hash == hash_token(token))
                    )
                ).scalar_one()
                row.expires_at = utcnow() - timedelta(days=1)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_run())


def _count_sessions(db_path: Path) -> int:
    async def _run() -> int:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                return await _session_count(db)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_boot_sweeps_expired_sessions(tmp_path: Path) -> None:
    db_path = tmp_path / "tasterr.db"
    _seed_expired_and_valid(db_path)
    settings = Settings.model_validate(
        {"database_path": db_path, "static_dir": tmp_path / "static"}
    )

    with TestClient(create_app(settings)):
        pass

    assert _count_sessions(db_path) == 1

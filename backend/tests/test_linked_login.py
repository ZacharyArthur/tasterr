import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.crypto import decrypt_token
from tasterr.auth.login import (
    AccountConflict,
    ProvenAccount,
    complete_login,
    get_link,
    link_account,
    resolve_user,
)
from tasterr.auth.sessions import resolve_session, revoke_session
from tasterr.clients.plex import PlexCloudAccount
from tasterr.clients.seerr import SeerrClient, SeerrLogin, SeerrUser
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import LinkedAccount, User, UserSession, utcnow

SECRET = "local-test-key"
PLEX = ProvenAccount.plex(
    PlexCloudAccount(id=8, username="plex", title="Plex name", thumb="thumb"), "token"
)
SEERR = SeerrLogin(SeerrUser(id=7, displayName="Seerr name", avatar="avatar"), "cookie")


@pytest.fixture
async def maker(tmp_path: Path) -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    engine = create_engine(tmp_path / "login.db")
    await upgrade_to_head(engine)
    yield async_sessionmaker(engine, expire_on_commit=False)
    await engine.dispose()


async def test_new_returning_bridge_refresh_and_logout(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user, token = await complete_login(db, SECRET, ProvenAccount.seerr(SEERR), SEERR, None)
        original_id = user.id
        user, _ = await complete_login(db, SECRET, PLEX, SEERR, None)
        assert user.id == original_id
        assert user.display_name == "Seerr name" and user.avatar_url == "avatar"
        link = await get_link(db, user.id, "plex")
        assert link is not None
        assert decrypt_token(SECRET, link.credential_enc or "") == "token"
        replacement = ProvenAccount("plex", "8", "updated", None, "fresh-token")
        changed_login = SeerrLogin(SEERR.user, "fresh-cookie")
        await complete_login(db, SECRET, replacement, changed_login, None)
        assert decrypt_token(SECRET, link.credential_enc or "") == "fresh-token"
        seerr_link = await get_link(db, user.id, "seerr")
        assert seerr_link is not None
        assert decrypt_token(SECRET, seerr_link.credential_enc or "") == "fresh-cookie"
        session = await resolve_session(db, token)
        assert session is not None
        await revoke_session(db, session.session)
        assert (await get_link(db, user.id, "plex")) is link
        assert {"seerr_cookie", "plex_token_enc"}.isdisjoint(UserSession.__table__.columns.keys())
        await db.delete(link)
        await db.commit()
        assert await get_link(db, user.id, "plex") is None


async def test_mismatch_unlink_flag_and_manual_relink(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        user = await resolve_user(db, SECRET, PLEX, SEERR)
        mismatched = SeerrLogin(SeerrUser(id=90, displayName="other"), "other-cookie")
        await resolve_user(db, SECRET, PLEX, mismatched)
        link = await get_link(db, user.id, "seerr")
        assert link is not None and link.external_id == "7"
        assert decrypt_token(SECRET, link.credential_enc or "") == "cookie"
        await db.delete(link)
        user.seerr_unlinked_at = utcnow()
        await db.commit()
        await resolve_user(db, SECRET, PLEX, SEERR)
        assert await get_link(db, user.id, "seerr") is None
        await link_account(db, SECRET, user.id, ProvenAccount.seerr(SEERR))
        user.seerr_unlinked_at = None
        await db.commit()
        assert await get_link(db, user.id, "seerr") is not None


async def test_bridge_conflict(
    maker: async_sessionmaker[AsyncSession],
) -> None:
    async with maker() as db:
        await resolve_user(db, SECRET, PLEX, SEERR)
        with pytest.raises(AccountConflict):
            await resolve_user(
                db, SECRET, ProvenAccount("plex", "99", "other", None, "token"), SEERR
            )
        await db.rollback()
        assert len((await db.scalars(select(User))).all()) == 1
        assert len((await db.scalars(select(LinkedAccount))).all()) == 2


@pytest.mark.parametrize("bridge", [False, True])
async def test_concurrent_signins_converge(
    maker: async_sessionmaker[AsyncSession], bridge: bool
) -> None:
    async def login(account: ProvenAccount) -> int:
        async with maker() as db:
            user = await resolve_user(db, SECRET, account, SEERR)
            return user.id

    ids = await asyncio.gather(login(PLEX), login(ProvenAccount.seerr(SEERR) if bridge else PLEX))
    assert ids[0] == ids[1]
    async with maker() as db:
        assert len((await db.scalars(select(User))).all()) == 1


@pytest.mark.parametrize(
    "status,previous,expected",
    [
        (200, False, True),
        (404, True, False),
        (500, True, False),
        (503, True, True),
        (503, False, False),
    ],
)
async def test_admin_checks_after_resolution_commit(
    maker: async_sessionmaker[AsyncSession],
    status: int,
    previous: bool,
    expected: bool,
) -> None:
    async with maker() as db:
        user = await resolve_user(db, SECRET, PLEX, SEERR)
        user.is_admin = previous
        await db.commit()

        async def response(_: httpx.Request) -> httpx.Response:
            assert not db.dirty and not db.new
            async with maker() as observer:
                assert await get_link(observer, user.id, "plex") is not None
                other = User(display_name="independent writer")
                observer.add(other)
                await observer.commit()
            return httpx.Response(status, json={"id": 7, "permissions": 2})

        async with httpx.AsyncClient(transport=httpx.MockTransport(response)) as http:
            user, _ = await complete_login(
                db, SECRET, PLEX, SEERR, SeerrClient(http, "http://seerr", "key")
            )
        assert user.is_admin is expected


async def test_plex_only_display_fallback(maker: async_sessionmaker[AsyncSession]) -> None:
    async with maker() as db:
        user, _ = await complete_login(db, SECRET, PLEX, None, None)
        assert (user.display_name, user.avatar_url) == ("Plex name", "thumb")

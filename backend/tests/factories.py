"""Linked identities and credentials for local test fixtures."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.crypto import encrypt_token
from tasterr.auth.sessions import mint_session
from tasterr.db.models import LinkedAccount, User


async def user_with_links(
    db: AsyncSession,
    *,
    seerr_user_id: int,
    display_name: str,
    auth_type: str,
    avatar_url: str | None = None,
    is_admin: bool = False,
    taste_onboarding_seen: bool = False,
) -> User:
    user = User(
        display_name=display_name,
        avatar_url=avatar_url,
        is_admin=is_admin,
        taste_onboarding_seen=taste_onboarding_seen,
    )
    db.add(user)
    await db.flush()
    db.add(
        LinkedAccount(
            user_id=user.id,
            provider="seerr",
            external_id=str(seerr_user_id),
            display_name=display_name,
            avatar_url=avatar_url,
        )
    )
    if auth_type == "plex":
        db.add(
            LinkedAccount(
                user_id=user.id,
                provider="plex",
                external_id=str(seerr_user_id),
                display_name=display_name,
            )
        )
    return user


async def mint_linked_session(
    db: AsyncSession,
    user_id: int,
    cookie: str,
    plex_token_enc: str | None,
) -> str:
    links = (await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user_id))).all()
    for link in links:
        if link.provider == "seerr":
            link.credential_enc = encrypt_token("test-secret-key", cookie)
        elif plex_token_enc is not None:
            link.credential_enc = plex_token_enc
    return await mint_session(db, user_id)


async def plex_link(db: AsyncSession, user_id: int) -> LinkedAccount:
    return (
        await db.scalars(
            select(LinkedAccount).where(
                LinkedAccount.user_id == user_id,
                LinkedAccount.provider == "plex",
            )
        )
    ).one()

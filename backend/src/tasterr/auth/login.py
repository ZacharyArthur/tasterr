"""Shared login pipeline: Seerr identity → user upsert → session mint (SPEC §4.1)."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.crypto import encrypt_token
from tasterr.auth.sessions import mint_session
from tasterr.clients.seerr import SeerrLogin
from tasterr.db.models import User, utcnow

# Seerr permission bitmask: bit 2 = ADMIN (confirmed by the auth spike, 3.3.0).
ADMIN_PERMISSION = 2


async def upsert_user(db: AsyncSession, login: SeerrLogin, auth_type: str) -> User:
    """Create or refresh the user keyed by Seerr id. Admin is re-derived on
    every login — never cached across logins (SPEC §4.4)."""
    seerr_user = login.user
    user = (
        await db.execute(select(User).where(User.seerr_user_id == seerr_user.id))
    ).scalar_one_or_none()
    is_admin = bool(seerr_user.permissions & ADMIN_PERMISSION)
    now = utcnow()
    if user is None:
        user = User(
            seerr_user_id=seerr_user.id,
            display_name=seerr_user.resolved_display_name,
            avatar_url=seerr_user.avatar,
            auth_type=auth_type,
            is_admin=is_admin,
            created_at=now,
            last_login_at=now,
        )
        db.add(user)
    else:
        user.display_name = seerr_user.resolved_display_name
        user.avatar_url = seerr_user.avatar
        user.auth_type = auth_type
        user.is_admin = is_admin
        user.last_login_at = now
    await db.flush()
    return user


async def complete_login(
    db: AsyncSession,
    secret_key: str,
    login: SeerrLogin,
    auth_type: str,
    plex_token: str | None,
) -> tuple[User, str]:
    """Both login paths converge here. Returns the user and the raw session
    token — it exists nowhere else but the caller's Set-Cookie header."""
    user = await upsert_user(db, login, auth_type)
    plex_token_enc = encrypt_token(secret_key, plex_token) if plex_token is not None else None
    token = await mint_session(db, user.id, login.cookie, plex_token_enc)
    return user, token

"""Server-side session store: hashed tokens, sliding expiry, trivial revocation."""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.db.models import User, UserSession, utcnow

SESSION_TTL = timedelta(days=30)
# Persist the slide at most hourly: ±1h precision on a 30-day window is
# immaterial and avoids a DB write on every authenticated request.
SLIDE_AFTER = timedelta(hours=1)


def new_token() -> str:
    return secrets.token_urlsafe(32)  # 256 bits


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


async def mint_session(
    db: AsyncSession,
    user_id: int,
    seerr_cookie: str,
    plex_token_enc: str | None,
) -> str:
    """Create a session row and return the raw token — the only place it exists
    outside the Set-Cookie header. Every login mints fresh (no fixation)."""
    token = new_token()
    now = utcnow()
    db.add(
        UserSession(
            token_hash=hash_token(token),
            user_id=user_id,
            seerr_cookie=seerr_cookie,
            plex_token_enc=plex_token_enc,
            created_at=now,
            expires_at=now + SESSION_TTL,
            last_seen_at=now,
        )
    )
    await db.commit()
    return token


async def resolve_session(db: AsyncSession, token: str) -> tuple[UserSession, User] | None:
    """Validate a raw token: exact-match lookup on its one-way hash, so no
    secret-dependent comparison happens in our code. Expired rows are deleted
    on touch; activity slides expiry (throttled)."""
    row = (
        await db.execute(
            select(UserSession, User)
            .join(User, UserSession.user_id == User.id)
            .where(UserSession.token_hash == hash_token(token))
        )
    ).first()
    if row is None:
        return None
    session, user = row[0], row[1]

    now = utcnow()
    if session.expires_at <= now:
        await db.delete(session)
        await db.commit()
        return None
    if now - session.last_seen_at >= SLIDE_AFTER:
        session.last_seen_at = now
        session.expires_at = now + SESSION_TTL
        await db.commit()
    return session, user


async def revoke_session(db: AsyncSession, session: UserSession) -> None:
    await db.delete(session)
    await db.commit()


async def sweep_expired(db: AsyncSession) -> None:
    """Boot-time cleanup; per-request expiry handling covers the steady state."""
    await db.execute(delete(UserSession).where(UserSession.expires_at <= utcnow()))
    await db.commit()

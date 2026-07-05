"""Request dependencies: DB session, current user (default-deny), admin, CSRF origin."""

from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.cookies import COOKIE_NAME, set_session_cookie
from tasterr.auth.sessions import resolve_session
from tasterr.db.models import User, UserSession


async def get_db(request: Request) -> AsyncGenerator[AsyncSession]:
    maker = cast("async_sessionmaker[AsyncSession]", request.app.state.sessionmaker)
    async with maker() as db:
        yield db


@dataclass
class AuthedSession:
    user: User
    session: UserSession


async def require_session(
    request: Request, response: Response, db: Annotated[AsyncSession, Depends(get_db)]
) -> AuthedSession:
    token = request.cookies.get(COOKIE_NAME)
    if token is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    resolved = await resolve_session(db, token)
    if resolved is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    if resolved.slid:
        # The server-side window slid; re-issue the cookie so its Max-Age
        # slides too — otherwise the browser drops it 30 days after login.
        set_session_cookie(response, token, secure=request.url.scheme == "https")
    return AuthedSession(user=resolved.user, session=resolved.session)


async def require_admin(
    authed: Annotated[AuthedSession, Depends(require_session)],
) -> AuthedSession:
    if not authed.user.is_admin:
        raise HTTPException(status_code=403, detail="Admin required")
    return authed


def require_same_origin(request: Request) -> None:
    """CSRF guard for mutations (SPEC §9). Browsers always send fetch metadata
    (or at least Origin); requests carrying neither are non-browser clients and
    pass — CSRF is a browser attack. SameSite=Lax is the independent second layer.
    """
    site = request.headers.get("sec-fetch-site")
    if site is not None:
        if site in ("same-origin", "none"):
            return
        raise HTTPException(status_code=403, detail="Cross-origin request rejected")
    origin = request.headers.get("origin")
    if origin is not None:
        # Full-origin comparison (scheme + host + port); the request scheme is
        # proxy-header aware, so it matches what the browser put in Origin.
        host = request.headers.get("host", "")
        if origin.lower() != f"{request.url.scheme}://{host}".lower():
            raise HTTPException(status_code=403, detail="Cross-origin request rejected")

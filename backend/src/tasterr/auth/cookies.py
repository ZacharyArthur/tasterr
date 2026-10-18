"""Session cookie helper: HttpOnly, SameSite=Lax, Secure on HTTPS (SPEC §4.2).

`secure` follows the request scheme — hard-coding it would break plain-HTTP
LAN deployments; uvicorn's proxy-header handling makes the scheme correct
behind the Cloudflare tunnel.
"""

from datetime import datetime

from fastapi import Response

from tasterr.auth.sessions import SESSION_TTL
from tasterr.db.models import utcnow

COOKIE_NAME = "tasterr_session"


def set_session_cookie(
    response: Response, token: str, *, secure: bool, expires_at: datetime | None = None
) -> None:
    max_age = int(SESSION_TTL.total_seconds())
    if expires_at is not None:
        max_age = max(0, int((expires_at - utcnow()).total_seconds()))
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=max_age,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def clear_session_cookie(response: Response, *, secure: bool) -> None:
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=secure,
        path="/",
    )


def session_cookie_header(token: str, *, secure: bool, expires_at: datetime) -> str:
    """The full Set-Cookie header value, for code writing raw ASGI headers."""
    response = Response()
    set_session_cookie(response, token, secure=secure, expires_at=expires_at)
    return response.headers["set-cookie"]

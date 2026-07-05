"""Session cookie helper: HttpOnly, SameSite=Lax, Secure on HTTPS (SPEC §4.2).

`secure` follows the request scheme — hard-coding it would break plain-HTTP
LAN deployments; uvicorn's proxy-header handling makes the scheme correct
behind the Cloudflare tunnel.
"""

from fastapi import Response

from tasterr.auth.sessions import SESSION_TTL

COOKIE_NAME = "tasterr_session"


def set_session_cookie(response: Response, token: str, *, secure: bool) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=int(SESSION_TTL.total_seconds()),
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


def session_cookie_header(token: str, *, secure: bool) -> str:
    """The full Set-Cookie header value, for code writing raw ASGI headers."""
    response = Response()
    set_session_cookie(response, token, secure=secure)
    return response.headers["set-cookie"]

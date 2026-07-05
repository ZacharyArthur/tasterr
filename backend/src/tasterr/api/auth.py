"""Auth endpoints: Plex PIN flow, local login, me, logout (SPEC §4).

Failure bodies are deliberately generic: no upstream bodies, no internal URLs,
no user enumeration. Login attempts are logged by outcome only — credentials,
tokens, and cookies never appear in logs.
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.auth.cookies import clear_session_cookie, set_session_cookie
from tasterr.auth.crypto import plex_client_identifier
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.login import complete_login
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import revoke_session
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexAuthClient
from tasterr.clients.seerr import SeerrAuthClient
from tasterr.db.models import User
from tasterr.settings import Settings, get_settings

logger = logging.getLogger(__name__)

router = APIRouter()

PIN_NOT_FOUND = "Unknown or expired sign-in attempt"
UPSTREAM_DOWN = "Sign-in service unavailable"


class UserResponse(BaseModel):
    id: int
    display_name: str
    avatar_url: str | None
    is_admin: bool

    @classmethod
    def from_user(cls, user: User) -> "UserResponse":
        return cls(
            id=user.id,
            display_name=user.display_name,
            avatar_url=user.avatar_url,
            is_admin=user.is_admin,
        )


class PinCreateResponse(BaseModel):
    pin_id: str  # opaque poll handle — never the raw plex.tv PIN id
    auth_url: str


class PinPollResponse(BaseModel):
    status: Literal["pending", "ok"]
    user: UserResponse | None = None


class LocalLoginRequest(BaseModel):
    email: str
    password: str


@dataclass
class AuthContext:
    secret_key: str
    plex: PlexAuthClient
    seerr: SeerrAuthClient
    pins: PinStore


def get_auth_context(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AuthContext:
    """Auth requires Seerr and the secret key; fail loudly at this boundary
    (M0 decision: unconfigured integrations degrade, never crash boot)."""
    secret = settings.tasterr_secret_key
    if secret is None or not settings.seerr_configured or settings.seerr_internal_url is None:
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    secret_key = secret.get_secret_value()
    return AuthContext(
        secret_key=secret_key,
        plex=PlexAuthClient(request.app.state.http, plex_client_identifier(secret_key)),
        seerr=SeerrAuthClient(request.app.state.http, settings.seerr_internal_url),
        pins=cast("PinStore", request.app.state.pin_store),
    )


def login_rate_limit(request: Request) -> None:
    bucket = cast("TokenBucket", request.app.state.login_bucket)
    key = request.client.host if request.client else "unknown"
    if not bucket.allow(key):
        raise HTTPException(status_code=429, detail="Too many attempts")


def _set_cookie(request: Request, response: Response, token: str) -> None:
    set_session_cookie(response, token, secure=request.url.scheme == "https")


@router.post(
    "/auth/plex/pin",
    dependencies=[Depends(require_same_origin), Depends(login_rate_limit)],
)
async def create_plex_pin(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
) -> PinCreateResponse:
    try:
        pin = await ctx.plex.create_pin()
    except (UpstreamRejected, UpstreamUnavailable) as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    handle = ctx.pins.create(pin.id)
    return PinCreateResponse(pin_id=handle, auth_url=ctx.plex.auth_url(pin.code))


# Unauthenticated by nature (pre-login) and exempt from the tight login bucket:
# it fires every ~2s by design and requires an unguessable 256-bit handle.
@router.get("/auth/plex/pin/{pin_id}")
async def poll_plex_pin(
    pin_id: str,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> PinPollResponse:
    plex_pin_id = ctx.pins.get(pin_id)
    if plex_pin_id is None:
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND)

    try:
        plex_token = await ctx.plex.poll_pin(plex_pin_id)
    except UpstreamRejected as error:  # plex.tv: PIN expired or unknown
        ctx.pins.consume(pin_id)
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND) from error
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    if plex_token is None:
        return PinPollResponse(status="pending")

    try:
        login = await ctx.seerr.login_plex(plex_token)
    except UpstreamRejected as error:  # Seerr refused this Plex account
        ctx.pins.consume(pin_id)
        logger.info("auth: plex login rejected by seerr")
        raise HTTPException(status_code=401, detail="Sign-in failed") from error
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error

    ctx.pins.consume(pin_id)
    user, token = await complete_login(db, ctx.secret_key, login, "plex", plex_token)
    _set_cookie(request, response, token)
    logger.info("auth: plex login succeeded user_id=%s", user.id)
    return PinPollResponse(status="ok", user=UserResponse.from_user(user))


@router.post(
    "/auth/local",
    dependencies=[Depends(require_same_origin), Depends(login_rate_limit)],
)
async def local_login(
    payload: LocalLoginRequest,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserResponse:
    try:
        login = await ctx.seerr.login_local(payload.email, payload.password)
    except UpstreamRejected as error:
        # Identical body for unknown account and wrong password: no enumeration.
        logger.info("auth: local login rejected")
        raise HTTPException(status_code=401, detail="Invalid email or password") from error
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error

    user, token = await complete_login(db, ctx.secret_key, login, "local", None)
    _set_cookie(request, response, token)
    logger.info("auth: local login succeeded user_id=%s", user.id)
    return UserResponse.from_user(user)


@router.get("/auth/me")
def get_me(authed: Annotated[AuthedSession, Depends(require_session)]) -> UserResponse:
    # Local state only — no Seerr call per request (SPEC §4.4).
    return UserResponse.from_user(authed.user)


@router.post(
    "/auth/logout",
    status_code=204,
    dependencies=[Depends(require_same_origin)],
)
async def logout(
    request: Request,
    response: Response,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await revoke_session(db, authed.session)
    clear_session_cookie(response, secure=request.url.scheme == "https")

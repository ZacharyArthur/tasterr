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

from tasterr.api.taste import build_seerr, schedule_history
from tasterr.auth.cookies import clear_session_cookie, set_session_cookie
from tasterr.auth.crypto import plex_client_identifier
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.login import (
    CONFLICT_GUIDANCE,
    AccountConflict,
    ProvenAccount,
    complete_login,
)
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket, mutation_rate_limit
from tasterr.auth.sessions import revoke_session
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexAuthClient
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient
from tasterr.db.models import Provider, User
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


class PinPollRequest(BaseModel):
    pin_id: str  # opaque poll handle — never the raw plex.tv PIN id


class PinPollResponse(BaseModel):
    status: Literal["pending", "ok"]
    user: UserResponse | None = None


class LocalLoginRequest(BaseModel):
    email: str
    password: str


class AuthMethodsResponse(BaseModel):
    plex: bool
    seerr: bool


@dataclass
class AuthContext:
    secret_key: str
    plex: PlexAuthClient
    seerr: SeerrAuthClient | None
    pins: PinStore
    seerr_read: SeerrClient | None = None


def get_auth_context(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> AuthContext:
    secret = settings.tasterr_secret_key
    if secret is None or not settings.plex_configured:
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    secret_key = secret.get_secret_value()
    return AuthContext(
        secret_key=secret_key,
        plex=PlexAuthClient(request.app.state.http, plex_client_identifier(secret_key)),
        seerr=SeerrAuthClient(request.app.state.http, settings.seerr_internal_url)
        if settings.seerr_configured and settings.seerr_internal_url is not None
        else None,
        pins=cast("PinStore", request.app.state.pin_store),
        seerr_read=build_seerr(request, settings),
    )


def provider_available(settings: Settings, provider: Provider) -> bool:
    return settings.tasterr_secret_key is not None and (
        settings.plex_configured if provider == "plex" else settings.seerr_configured
    )


@router.get("/auth/methods", response_model=AuthMethodsResponse)
def auth_methods(settings: Annotated[Settings, Depends(get_settings)]) -> AuthMethodsResponse:
    return AuthMethodsResponse(
        plex=provider_available(settings, "plex"),
        seerr=provider_available(settings, "seerr"),
    )


def get_seerr_auth_context(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    if not provider_available(settings, "seerr"):
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    return ctx


def get_plex_auth_context(
    ctx: Annotated[AuthContext, Depends(get_auth_context)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> AuthContext:
    if not provider_available(settings, "plex"):
        raise HTTPException(status_code=503, detail="Authentication unavailable")
    return ctx


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
    ctx: Annotated[AuthContext, Depends(get_plex_auth_context)],
) -> PinCreateResponse:
    try:
        pin = await ctx.plex.create_pin()
    except (UpstreamRejected, UpstreamUnavailable) as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    handle = ctx.pins.create(pin.id)
    return PinCreateResponse(pin_id=handle, auth_url=ctx.plex.auth_url(pin.code))


# Unauthenticated by nature (pre-login) and exempt from the tight login bucket:
# it fires every ~2s by design and is gated by an unguessable 256-bit handle.
# A POST (not GET) with the same-origin guard below closes a login-CSRF / session
# swap: a cross-site page can no longer trigger a session-minting completion by
# top-level navigation, because the guard rejects cross-site fetch metadata before
# any upstream call, handle consumption, or cookie change.
@router.post(
    "/auth/plex/pin/poll",
    dependencies=[Depends(require_same_origin)],
)
async def poll_plex_pin(
    payload: PinPollRequest,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_plex_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> PinPollResponse:
    pin_id = payload.pin_id
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

    # Atomically take the handle before the Seerr exchange: overlapping polls
    # on a claimed PIN mint exactly one session; the losers get the same
    # generic 404 as an expired handle.
    if ctx.pins.pop(pin_id) is None:
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND)

    try:
        plex_account = await ctx.plex.account(plex_token)
    except (UpstreamRejected, UpstreamUnavailable) as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error

    resources = None
    if settings.plex_server_id is not None:
        try:
            resources = await ctx.plex.resources(plex_token)
        except (UpstreamRejected, UpstreamUnavailable) as error:
            raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
        if not any(item.client_identifier == settings.plex_server_id for item in resources):
            raise HTTPException(status_code=401, detail="Sign-in failed")

    login = None
    seerr_unavailable = False
    try:
        if ctx.seerr is not None:
            login = await ctx.seerr.login_plex(plex_token)
    except UpstreamRejected as error:  # Seerr refused this Plex account
        logger.info("auth: plex login rejected by seerr")
        if settings.plex_server_id is None:
            raise HTTPException(status_code=401, detail="Sign-in failed") from error
    except UpstreamUnavailable as error:
        if settings.plex_server_id is None:
            raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
        seerr_unavailable = True

    try:
        user, token = await complete_login(
            db,
            ctx.secret_key,
            ProvenAccount.plex(plex_account, plex_token),
            login,
            ctx.seerr_read,
            seerr_unavailable=seerr_unavailable,
            plex=ctx.plex,
            server_id=settings.plex_server_id,
            plex_resources=resources,
        )
    except UpstreamUnavailable as error:
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    except AccountConflict as error:
        raise HTTPException(status_code=409, detail=CONFLICT_GUIDANCE) from error
    _set_cookie(request, response, token)
    logger.info("auth: plex login succeeded")
    await schedule_history(request, settings, db, user.id)
    return PinPollResponse(status="ok", user=UserResponse.from_user(user))


@router.post(
    "/auth/local",
    dependencies=[Depends(require_same_origin), Depends(login_rate_limit)],
)
async def local_login(
    payload: LocalLoginRequest,
    request: Request,
    response: Response,
    ctx: Annotated[AuthContext, Depends(get_seerr_auth_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> UserResponse:
    assert ctx.seerr is not None
    try:
        login = await ctx.seerr.login_local(payload.email, payload.password)
    except UpstreamRejected as error:
        # Identical body for unknown account and wrong password: no enumeration.
        logger.info("auth: local login rejected")
        raise HTTPException(status_code=401, detail="Invalid email or password") from error
    except UpstreamUnavailable as error:
        logger.warning("auth: local login unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error

    try:
        user, token = await complete_login(
            db,
            ctx.secret_key,
            ProvenAccount.seerr(login),
            login,
            ctx.seerr_read,
            plex=ctx.plex,
            server_id=settings.plex_server_id,
        )
    except AccountConflict as error:
        raise HTTPException(status_code=409, detail=CONFLICT_GUIDANCE) from error
    _set_cookie(request, response, token)
    logger.info("auth: local login succeeded")
    await schedule_history(request, settings, db, user.id)
    return UserResponse.from_user(user)


@router.get("/auth/me")
def get_me(authed: Annotated[AuthedSession, Depends(require_session)]) -> UserResponse:
    # Local state only — no Seerr call per request (SPEC §4.4).
    return UserResponse.from_user(authed.user)


@router.post(
    "/auth/logout",
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def logout(
    request: Request,
    response: Response,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> None:
    await revoke_session(db, authed.session)
    clear_session_cookie(response, secure=request.url.scheme == "https")

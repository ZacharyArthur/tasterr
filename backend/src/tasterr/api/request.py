"""Request-as-user (SPEC §4.3/§6). Session-gated and CSRF-checked.

The request is proxied to Seerr with the member's own stored session cookie, so it
lands attributed to them under their quota. On Seerr's `403` (its invalid-session
signal — also its genuine permission-denied) the re-auth ladder runs at most once:
a Plex member re-authenticates silently with the stored encrypted token and retries;
a local member is asked to re-login. Every response carries a server-built Seerr
external link as a fallback (SPEC §9 — never assembled from input).
"""

import logging
from dataclasses import dataclass
from typing import Annotated, Literal

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import refresh_profile
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.catalog.availability import Availability, availability_from_code
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import MediaType, SeerrAuthClient, SeerrClient
from tasterr.recommend import store
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.request")
router = APIRouter()

RequestStatus = Literal["ok", "re_auth_required", "unavailable", "failed"]


class RequestBody(BaseModel):
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(ge=1)


class RequestResponse(BaseModel):
    """A single discriminated outcome the SPA branches on. `availability` is the new
    library status on success; `seerr_url` is the server-built "Request in Seerr"
    fallback (present whenever the external URL is configured)."""

    status: RequestStatus
    availability: Availability | None = None
    seerr_url: str | None = None


@dataclass
class SeerrRequestCtx:
    client: SeerrClient
    seerr_auth: SeerrAuthClient
    secret_key: str


def get_seerr_request_ctx(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SeerrRequestCtx | None:
    # None → requests unavailable (Seerr or the secret key unconfigured). The
    # session and CSRF guards run first, so an unauthenticated or cross-origin
    # caller is rejected before this builds anything (no Seerr call happens here).
    if (
        not settings.seerr_configured
        or settings.seerr_internal_url is None
        or settings.seerr_api_key is None
        or settings.tasterr_secret_key is None
    ):
        return None
    return SeerrRequestCtx(
        client=SeerrClient(
            request.app.state.http,
            settings.seerr_internal_url,
            settings.seerr_api_key.get_secret_value(),
        ),
        seerr_auth=SeerrAuthClient(request.app.state.http, settings.seerr_internal_url),
        secret_key=settings.tasterr_secret_key.get_secret_value(),
    )


SeerrRequestDep = Annotated[SeerrRequestCtx | None, Depends(get_seerr_request_ctx)]


@dataclass
class _Outcome:
    status: RequestStatus
    availability: Availability | None = None


@router.post(
    "/request",
    response_model=RequestResponse,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def create_request(
    payload: RequestBody,
    authed: Annotated[AuthedSession, Depends(require_session)],
    ctx: SeerrRequestDep,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
    runtime: RuntimeSettingsDep,
    request: Request,
) -> RequestResponse:
    seerr_url = _external_url(settings.seerr_external_url, payload.media_type, payload.tmdb_id)
    if ctx is None:
        return RequestResponse(status="unavailable", seerr_url=seerr_url)
    outcome = await _request_with_reauth(ctx, db, authed, payload.media_type, payload.tmdb_id)
    if outcome.status == "ok":
        await _record_request_signal(
            request,
            settings,
            runtime,
            db,
            authed.user.id,
            payload.media_type,
            payload.tmdb_id,
        )
    return RequestResponse(
        status=outcome.status, availability=outcome.availability, seerr_url=seerr_url
    )


async def _record_request_signal(
    request: Request,
    settings: Settings,
    runtime: RuntimeSettings,
    db: AsyncSession,
    user_id: int,
    media_type: MediaType,
    tmdb_id: int,
) -> None:
    """The authoritative `request` taste signal (SPEC §8) — recorded server-side
    so the SPA never self-reports it, and never the request response's fate."""
    try:
        await store.record_signal(db, user_id, media_type, tmdb_id, "request")
        await db.commit()
    except Exception:  # the Seerr request already succeeded; never fail it now
        logger.exception("request: taste signal write failed user_id=%s", user_id)
        await db.rollback()
        return
    await refresh_profile(request, settings, db, user_id, runtime)


def _external_url(external: str | None, media_type: MediaType, tmdb_id: int) -> str | None:
    if external is None:
        return None
    return f"{external.rstrip('/')}/{media_type}/{tmdb_id}"


async def _request_with_reauth(
    ctx: SeerrRequestCtx,
    db: AsyncSession,
    authed: AuthedSession,
    media_type: MediaType,
    tmdb_id: int,
) -> _Outcome:
    try:
        code = await ctx.client.create_request(authed.session.seerr_cookie, media_type, tmdb_id)
        return _Outcome("ok", availability_from_code(code))
    except UpstreamUnavailable:
        return _Outcome("failed")
    except UpstreamRejected as error:
        if error.status_code != 403:
            return _Outcome("failed")  # a non-403 rejection is not a session problem

    # 403 — an invalid session or a genuine denial. Re-auth at most once.
    if authed.session.plex_token_enc is None:
        return _Outcome("re_auth_required")  # local member: the SPA re-logs them in
    new_cookie = await _reauth_plex(ctx, db, authed)
    if new_cookie is None:
        return _Outcome("failed")  # re-auth itself failed
    try:
        code = await ctx.client.create_request(new_cookie, media_type, tmdb_id)
        return _Outcome("ok", availability_from_code(code))
    except (UpstreamRejected, UpstreamUnavailable):
        return _Outcome("failed")  # still 403 → genuine denial (quota/permission)


async def _reauth_plex(ctx: SeerrRequestCtx, db: AsyncSession, authed: AuthedSession) -> str | None:
    """Silently refresh the member's Seerr session from their stored Plex token and
    persist the new cookie. Returns the fresh cookie, or None if re-auth is not
    possible (unreadable token or Seerr refusal)."""
    enc = authed.session.plex_token_enc
    if enc is None:
        return None
    try:
        token = decrypt_token(ctx.secret_key, enc)
    except InvalidToken:
        return None  # ciphertext unreadable (e.g. the secret key was rotated)
    try:
        login = await ctx.seerr_auth.login_plex(token)
    except (UpstreamRejected, UpstreamUnavailable):
        return None
    authed.session.seerr_cookie = login.cookie
    await db.commit()
    logger.info("request: silent re-auth refreshed seerr session user_id=%s", authed.user.id)
    return login.cookie

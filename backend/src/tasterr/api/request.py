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
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import refresh_profile
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.catalog.availability import Availability, availability_from_code
from tasterr.clients.errors import UpstreamError, UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import MediaType, SeerrAuthClient, SeerrClient
from tasterr.recommend import store
from tasterr.recommend.signals import MAX_TMDB_ID
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.request")
router = APIRouter()

# Generous ceiling for a season number; long-running daily shows reach the hundreds.
MAX_SEASON_NUMBER = 1000

RequestStatus = Literal["ok", "re_auth_required", "unavailable", "failed"]


class RequestBody(BaseModel):
    media_type: Literal["movie", "tv"]
    tmdb_id: int = Field(ge=1, le=MAX_TMDB_ID)
    is_4k: bool = False
    # Optional non-default destination (request-destination-override). All three
    # or none — a partial override is rejected the same as an unmatched one.
    server_id: int | None = Field(default=None, ge=0, le=MAX_TMDB_ID)
    profile_id: int | None = Field(default=None, ge=0, le=MAX_TMDB_ID)
    root_folder: str | None = Field(default=None, min_length=1, max_length=4096)
    # Optional TV season list (tv-season-selection); 0 is Specials. Omitted
    # keeps Seerr's whole-series "all".
    seasons: list[Annotated[int, Field(ge=0, le=MAX_SEASON_NUMBER)]] | None = Field(
        default=None, min_length=1, max_length=MAX_SEASON_NUMBER
    )

    @field_validator("seasons")
    @classmethod
    def _unique_seasons(cls, value: list[int] | None) -> list[int] | None:
        if value is not None and len(set(value)) != len(value):
            raise ValueError("duplicate season")
        return sorted(value) if value is not None else None


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
    has_override = any(
        value is not None for value in (payload.server_id, payload.profile_id, payload.root_folder)
    )
    if has_override and any(
        value is None for value in (payload.server_id, payload.profile_id, payload.root_folder)
    ):
        raise HTTPException(status_code=422, detail="Incomplete destination override")
    if payload.seasons is not None and payload.media_type != "tv":
        raise HTTPException(status_code=422, detail="Seasons apply to TV requests only")
    try:
        user = await ctx.client.user(authed.user.seerr_user_id)
        if not user.can_request(payload.media_type, is_4k=payload.is_4k):
            raise HTTPException(status_code=403, detail="Request permission required")
        if has_override and not user.can_override:
            raise HTTPException(status_code=403, detail="Advanced request permission required")
        info = await ctx.client.media_status(payload.media_type, payload.tmdb_id)
        code = (info.status_4k if payload.is_4k else info.status) if info else 0
        if code in (2, 3, 4, 5):
            raise HTTPException(
                status_code=409, detail="This version is already requested or available"
            )
        await _validate_override(
            ctx.client,
            payload.media_type,
            payload.server_id,
            payload.profile_id,
            payload.root_folder,
            is_4k=payload.is_4k,
        )
    except UpstreamError:
        return RequestResponse(status="failed", seerr_url=seerr_url)
    outcome = await _request_with_reauth(
        ctx,
        db,
        authed,
        payload.media_type,
        payload.tmdb_id,
        is_4k=payload.is_4k,
        server_id=payload.server_id,
        profile_id=payload.profile_id,
        root_folder=payload.root_folder,
        seasons=payload.seasons,
    )
    if outcome.status == "ok":
        await request.app.state.seerr_cache.invalidate(
            f"seerr:avail:{payload.media_type}:{payload.tmdb_id}"
        )
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


async def _validate_override(
    client: SeerrClient,
    media_type: MediaType,
    server_id: int | None,
    profile_id: int | None,
    root_folder: str | None,
    *,
    is_4k: bool,
) -> None:
    """Validate a 4K default or the selected override; preserve upstream failures."""
    if server_id is None and not is_4k:
        return
    servers = await client.list_servers(media_type)
    if server_id is None:
        if not any(s.is_4k and s.is_default for s in servers):
            raise HTTPException(status_code=422, detail="No default 4K destination configured")
        return
    server = next((s for s in servers if s.id == server_id and s.is_4k == is_4k), None)
    if server is None:
        raise HTTPException(status_code=422, detail="Unknown request destination")
    detail = await client.server_destinations(media_type, server_id)
    if (
        detail.server.id == server_id
        and detail.server.is_4k == is_4k
        and any(p.id == profile_id for p in detail.profiles)
        and any(rf.path == root_folder for rf in detail.root_folders)
    ):
        return
    raise HTTPException(status_code=422, detail="Unknown request destination")


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
        logger.exception("request: taste signal write failed")
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
    *,
    is_4k: bool = False,
    server_id: int | None = None,
    profile_id: int | None = None,
    root_folder: str | None = None,
    seasons: list[int] | None = None,
) -> _Outcome:
    try:
        code = await ctx.client.create_request(
            authed.session.seerr_cookie,
            media_type,
            tmdb_id,
            is_4k=is_4k,
            server_id=server_id,
            profile_id=profile_id,
            root_folder=root_folder,
            seasons=seasons,
        )
        return _Outcome("ok", availability_from_code(code, is_4k=is_4k))
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
        code = await ctx.client.create_request(
            new_cookie,
            media_type,
            tmdb_id,
            is_4k=is_4k,
            server_id=server_id,
            profile_id=profile_id,
            root_folder=root_folder,
            seasons=seasons,
        )
        return _Outcome("ok", availability_from_code(code, is_4k=is_4k))
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
    logger.info("request: silent re-auth refreshed seerr session")
    return login.cookie

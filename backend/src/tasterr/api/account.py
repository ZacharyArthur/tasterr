"""Owner-scoped account links, proven by authentication in each request."""

import logging
from datetime import datetime
from typing import Annotated, Literal

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.auth import (
    PIN_NOT_FOUND,
    UPSTREAM_DOWN,
    AuthContext,
    JellyfinLoginRequest,
    PinCreateResponse,
    PinPollRequest,
    get_jellyfin_auth_context,
    get_plex_auth_context,
    get_seerr_auth_context,
    login_rate_limit,
    provider_available,
)
from tasterr.api.taste import (
    cancel_jellyfin_history,
    cancel_plex_history,
    cancel_seed,
    cancel_source_history,
    history_guard,
    schedule_history,
)
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import AuthedSession, get_db, require_same_origin, require_session
from tasterr.auth.jellyfin import authenticate_and_logout
from tasterr.auth.login import (
    CONFLICT_GUIDANCE,
    AccountConflict,
    ProvenAccount,
    get_link,
    link_account,
)
from tasterr.auth.ratelimit import mutation_rate_limit
from tasterr.catalog.plex import continue_watching_key
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.db.models import LinkedAccount, Provider, Signal, User, utcnow
from tasterr.recommend import store
from tasterr.recommend.signals import SOURCE_KINDS, TasteSource
from tasterr.recommend.store import invalidate_profile
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.account")
router = APIRouter(dependencies=[Depends(require_session)])
Db = Annotated[AsyncSession, Depends(get_db)]
Member = Annotated[AuthedSession, Depends(require_session)]
Config = Annotated[Settings, Depends(get_settings)]
Auth = Annotated[AuthContext, Depends(get_plex_auth_context)]
SeerrAuth = Annotated[AuthContext, Depends(get_seerr_auth_context)]
JellyfinAuth = Annotated[AuthContext, Depends(get_jellyfin_auth_context)]


class AccountProvider(BaseModel):
    provider: Provider
    available: bool
    linked: bool
    display_name: str | None = None
    linked_at: datetime | None = None
    can_unlink: bool = False


class AccountResponse(BaseModel):
    providers: list[AccountProvider]
    taste_sources: dict[TasteSource, bool]


class LinkPollResponse(BaseModel):
    status: Literal["pending", "ok"]


class SeerrLinkBody(BaseModel):
    method: Literal["plex", "jellyfin", "local"]
    username: str = Field(default="", max_length=320)
    email: str = Field(default="", max_length=320)
    password: str = Field(default="", max_length=4096)


class UnlinkBody(BaseModel):
    delete_history: bool = False


class DeleteAccountBody(BaseModel):
    confirm: str = Field(max_length=4096)


class TasteSourceBody(BaseModel):
    source: TasteSource
    enabled: bool


@router.post(
    "/account/taste-sources",
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def set_taste_source(
    payload: TasteSourceBody, authed: Member, db: Db, settings: Config, request: Request
) -> None:
    user_id = authed.user.id
    await db.commit()
    async with history_guard(request, user_id):
        if not payload.enabled:
            await cancel_source_history(request, user_id, payload.source)
        await db.execute(text("BEGIN IMMEDIATE"))
        changed = await store.set_source_enabled(db, user_id, payload.source, payload.enabled)
        if changed and payload.enabled and payload.source != "browsing":
            link = await get_link(db, user_id, payload.source)
            if link is not None:
                link.sync_attempted_at = None
                link.sync_synced_at = None
        await db.commit()
    if changed and payload.enabled and payload.source != "browsing":
        await schedule_history(request, settings, db, user_id, source=payload.source)


@router.post(
    "/account/taste-sources/{source}/clear",
    status_code=204,
    dependencies=[Depends(require_same_origin), Depends(mutation_rate_limit)],
)
async def clear_taste_source(source: TasteSource, authed: Member, db: Db, request: Request) -> None:
    user_id = authed.user.id
    await db.commit()
    async with history_guard(request, user_id):
        await cancel_source_history(request, user_id, source)
        await db.execute(text("BEGIN IMMEDIATE"))
        await db.execute(
            delete(Signal).where(Signal.user_id == user_id, Signal.kind.in_(SOURCE_KINDS[source]))
        )
        await invalidate_profile(db, user_id)
        await db.commit()


@router.get("/account", response_model=AccountResponse)
async def account_summary(authed: Member, db: Db, settings: Config) -> AccountResponse:
    links = (
        await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == authed.user.id))
    ).all()
    retained_kinds = set(
        await db.scalars(select(Signal.kind).where(Signal.user_id == authed.user.id).distinct())
    )
    excluded = await store.excluded_sources(db, authed.user.id)
    return AccountResponse(
        taste_sources={source: source not in excluded for source in SOURCE_KINDS},
        providers=[
            AccountProvider(
                provider=provider,
                available=provider_available(settings, provider),
                linked=link is not None,
                display_name=link.display_name if link else None,
                linked_at=link.linked_at if link else None,
                can_unlink=link is not None
                and any(
                    other.provider != provider and provider_available(settings, other.provider)
                    for other in links
                ),
            )
            for provider in ("plex", "jellyfin", "seerr")
            if (link := next((item for item in links if item.provider == provider), None))
            is not None
            or provider_available(settings, provider)
            or bool(SOURCE_KINDS[provider] & retained_kinds)
        ],
    )


async def _save_link(
    request: Request,
    db: AsyncSession,
    settings: Settings,
    authed: AuthedSession,
    ctx: AuthContext,
    account: ProvenAccount,
) -> None:
    try:
        await link_account(db, ctx.secret_key, authed.user.id, account)
        if account.provider == "seerr":
            authed.user.seerr_unlinked_at = None
        await db.commit()
    except (AccountConflict, IntegrityError) as error:
        await db.rollback()
        logger.info("account: link %s refused", account.provider)
        raise HTTPException(status_code=409, detail=CONFLICT_GUIDANCE) from error
    logger.info("account: link %s succeeded", account.provider)
    await schedule_history(request, settings, db, authed.user.id)


@router.post(
    "/account/links/plex/pin",
    response_model=PinCreateResponse,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
        Depends(login_rate_limit),
    ],
)
async def create_link_pin(authed: Member, ctx: Auth) -> PinCreateResponse:
    try:
        pin = await ctx.plex.create_pin()
    except (UpstreamRejected, UpstreamUnavailable) as error:
        logger.info("account: create plex pin failed")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    logger.info("account: create plex pin succeeded")
    return PinCreateResponse(
        pin_id=ctx.pins.create(pin.id, session_hash=authed.session.token_hash),
        auth_url=ctx.plex.auth_url(pin.code),
    )


@router.post(
    "/account/links/plex/pin/poll",
    response_model=LinkPollResponse,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
    ],
)
async def poll_link_pin(
    payload: PinPollRequest, authed: Member, ctx: Auth, db: Db, settings: Config, request: Request
) -> LinkPollResponse:
    raw_pin = ctx.pins.get(payload.pin_id, session_hash=authed.session.token_hash)
    if raw_pin is None:
        logger.info("account: link plex refused")
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND)
    try:
        token = await ctx.plex.poll_pin(raw_pin)
    except UpstreamRejected as error:
        ctx.pins.consume(payload.pin_id)
        logger.info("account: link plex refused")
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND) from error
    except UpstreamUnavailable as error:
        logger.info("account: link plex unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    if token is None:
        return LinkPollResponse(status="pending")
    if ctx.pins.pop(payload.pin_id, session_hash=authed.session.token_hash) is None:
        logger.info("account: link plex refused")
        raise HTTPException(status_code=404, detail=PIN_NOT_FOUND)
    try:
        account = await ctx.plex.account(token)
    except (UpstreamRejected, UpstreamUnavailable) as error:
        logger.info("account: link plex unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    try:
        if settings.plex_server_id is not None:
            resources = await ctx.plex.resources(token)
            if not any(item.client_identifier == settings.plex_server_id for item in resources):
                raise HTTPException(status_code=403, detail="Account cannot be linked")
        else:
            assert ctx.seerr is not None
            await ctx.seerr.login_plex(token)
    except UpstreamRejected as error:
        logger.info("account: link plex refused")
        raise HTTPException(status_code=403, detail="Account cannot be linked") from error
    except UpstreamUnavailable as error:
        logger.info("account: link plex unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    await _save_link(request, db, settings, authed, ctx, ProvenAccount.plex(account, token))
    return LinkPollResponse(status="ok")


@router.post(
    "/account/links/seerr",
    status_code=204,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
        Depends(login_rate_limit),
    ],
)
async def link_seerr(
    payload: SeerrLinkBody,
    authed: Member,
    ctx: SeerrAuth,
    db: Db,
    settings: Config,
    request: Request,
) -> None:
    assert ctx.seerr is not None
    try:
        if payload.method == "local":
            login = await ctx.seerr.login_local(payload.email, payload.password)
        elif payload.method == "jellyfin":
            if not provider_available(settings, "jellyfin"):
                raise HTTPException(status_code=503, detail="Authentication unavailable")
            if not payload.password and not settings.jellyfin_allow_empty_password:
                raise UpstreamRejected(401)
            login = await ctx.seerr.login_jellyfin(payload.username, payload.password)
        else:
            plex = await get_link(db, authed.user.id, "plex")
            if plex is None or plex.credential_enc is None:
                logger.info("account: link seerr refused")
                raise HTTPException(status_code=409, detail="Connect Plex first")
            login = await ctx.seerr.login_plex(decrypt_token(ctx.secret_key, plex.credential_enc))
    except (UpstreamRejected, InvalidToken) as error:
        logger.info("account: link seerr refused")
        raise HTTPException(status_code=401, detail="Sign-in failed") from error
    except UpstreamUnavailable as error:
        logger.info("account: link seerr unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    await _save_link(request, db, settings, authed, ctx, ProvenAccount.seerr(login))


@router.post(
    "/account/links/jellyfin",
    status_code=204,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
        Depends(login_rate_limit),
    ],
)
async def link_jellyfin(
    payload: JellyfinLoginRequest,
    authed: Member,
    ctx: JellyfinAuth,
    db: Db,
    settings: Config,
    request: Request,
) -> None:
    assert ctx.jellyfin is not None
    try:
        user = await authenticate_and_logout(
            ctx.jellyfin,
            payload.username,
            payload.password,
            allow_empty_password=settings.jellyfin_allow_empty_password,
        )
    except UpstreamRejected as error:
        logger.info("account: link jellyfin refused")
        raise HTTPException(status_code=401, detail="Sign-in failed") from error
    except UpstreamUnavailable as error:
        logger.info("account: link jellyfin unavailable")
        raise HTTPException(status_code=502, detail=UPSTREAM_DOWN) from error
    await _save_link(request, db, settings, authed, ctx, ProvenAccount.jellyfin(user))


@router.post(
    "/account/links/{provider}/unlink",
    status_code=204,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
    ],
)
async def unlink_account(
    provider: Provider,
    payload: UnlinkBody,
    authed: Member,
    db: Db,
    settings: Config,
    request: Request,
) -> None:
    user_id = authed.user.id
    # Release the auth read before waiting, so it cannot block the current writer's commit.
    await db.commit()
    async with history_guard(request, user_id):
        await cancel_source_history(request, user_id, provider)
        await db.execute(text("BEGIN IMMEDIATE"))
        links = (
            await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user_id))
        ).all()
        link = next((item for item in links if item.provider == provider), None)
        if link is None:
            logger.info("account: unlink %s refused", provider)
            raise HTTPException(status_code=404, detail="Account is not linked")
        if not any(
            item.provider != provider and provider_available(settings, item.provider)
            for item in links
        ):
            logger.info("account: unlink %s refused", provider)
            raise HTTPException(status_code=409, detail="This is your only way to sign in")
        await db.delete(link)
        if provider == "seerr":
            authed.user.seerr_unlinked_at = utcnow()
        if payload.delete_history:
            await db.execute(
                delete(Signal).where(
                    Signal.user_id == user_id,
                    Signal.kind.in_(SOURCE_KINDS[provider]),
                )
            )
            await invalidate_profile(db, user_id)
        await db.commit()
        logger.info("account: unlink %s succeeded", provider)
        if provider == "plex":
            await request.app.state.catalog_cache.invalidate(continue_watching_key(user_id))


@router.post(
    "/account/delete",
    status_code=204,
    dependencies=[
        Depends(require_same_origin),
        Depends(mutation_rate_limit),
    ],
)
async def delete_account(
    payload: DeleteAccountBody, authed: Member, db: Db, request: Request
) -> None:
    if payload.confirm != authed.user.display_name:
        logger.info("account: delete refused")
        raise HTTPException(status_code=422, detail="Confirmation must match your display name")
    # A delayed cookie update could overwrite a newer sign-in in another tab.
    request.state.session_cookie_refresh = None
    user_id = authed.user.id
    await db.commit()
    async with history_guard(request, user_id):
        await cancel_seed(request, user_id)
        await cancel_plex_history(request, user_id)
        await cancel_jellyfin_history(request, user_id)
        await db.execute(delete(User).where(User.id == user_id))
        await db.commit()
        logger.info("account: delete succeeded")
        await request.app.state.catalog_cache.invalidate(continue_watching_key(user_id))

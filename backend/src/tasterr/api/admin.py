"""Admin-only runtime settings, catalog choices, and configured probes (M5)."""

import asyncio
from collections import Counter
from enum import StrEnum
from typing import Annotated

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import and_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.auth import (
    SEERR_LOGIN_SUPPORT_KEY,
    provider_configured,
    seerr_login_support,
    sign_in_offered,
)
from tasterr.api.catalog import CatalogDep
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import build_jellyfin, build_plex_media
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import (
    AuthedSession,
    get_db,
    require_admin,
    require_same_origin,
)
from tasterr.auth.login import get_link
from tasterr.auth.ratelimit import admin_rate_limit
from tasterr.catalog.models import RegionOption, ServiceOption
from tasterr.clients.errors import UpstreamError
from tasterr.clients.seerr import MediaServer, SeerrClient
from tasterr.clients.tmdb import CatalogNotConfigured, TmdbClient
from tasterr.db.models import LinkedAccount, User
from tasterr.db.runtime_settings import load_runtime_settings, save_runtime_settings
from tasterr.runtime_settings import (
    SIGN_IN_METHODS,
    DiscoverySetting,
    LanguageCode,
    RailTypeDescriptor,
    RuntimeSettings,
    SignInMethod,
    rail_type_descriptors,
)
from tasterr.settings import Settings, get_settings

router = APIRouter()


class SignInLinkCount(BaseModel):
    methods: list[SignInMethod]
    count: int


class SettingsResponse(BaseModel):
    settings: RuntimeSettings
    rail_types: list[RailTypeDescriptor]
    locked_fields: list[DiscoverySetting] = []
    configured_sign_in_methods: list[SignInMethod]
    sign_in_link_counts: list[SignInLinkCount]


async def settings_response(
    db: AsyncSession, settings: Settings, runtime: RuntimeSettings
) -> SettingsResponse:
    configured: list[SignInMethod] = [
        method for method in SIGN_IN_METHODS if provider_configured(settings, method)
    ]
    links: dict[int, set[str]] = {}
    for user_id, provider in await db.execute(
        select(User.id, LinkedAccount.provider).outerjoin(
            LinkedAccount,
            and_(LinkedAccount.user_id == User.id, LinkedAccount.provider.in_(configured)),
        )
    ):
        methods = links.setdefault(user_id, set())
        if provider is not None:
            methods.add(provider)
    counts: Counter[tuple[SignInMethod, ...]] = Counter(
        tuple(method for method in configured if method in linked) for linked in links.values()
    )
    return SettingsResponse(
        settings=runtime,
        rail_types=rail_type_descriptors(),
        locked_fields=settings.locked_discovery_fields,
        configured_sign_in_methods=configured,
        sign_in_link_counts=[
            SignInLinkCount(methods=list(methods), count=count)
            for methods, count in sorted(counts.items())
        ],
    )


class RegionsResponse(BaseModel):
    regions: list[RegionOption]


class LanguagesResponse(BaseModel):
    languages: list[LanguageCode]


class ServicesResponse(BaseModel):
    region: str
    services: list[ServiceOption]


class ConnectionTarget(StrEnum):
    TMDB = "tmdb"
    SEERR = "seerr"
    PLEX = "plex"
    JELLYFIN = "jellyfin"


class ConnectionTestRequest(BaseModel):
    target: ConnectionTarget


class ConnectionTestResponse(BaseModel):
    target: ConnectionTarget
    ok: bool
    detail: str


class SeerrIntegration(BaseModel):
    configured: bool
    media_server: MediaServer
    plex: bool | None
    jellyfin: bool | None
    local: bool | None


class IntegrationsResponse(BaseModel):
    seerr: SeerrIntegration
    plex_server_pinned: bool
    jellyfin_configured: bool


@router.get("/integrations", response_model=IntegrationsResponse)
async def get_integrations(
    request: Request,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> IntegrationsResponse:
    support = await seerr_login_support(request, settings)
    return IntegrationsResponse(
        seerr=SeerrIntegration(
            configured=settings.seerr_configured,
            media_server=support.media_server,
            plex=support.plex,
            jellyfin=support.jellyfin,
            local=support.local,
        ),
        plex_server_pinned=settings.plex_server_id is not None,
        jellyfin_configured=settings.jellyfin_configured,
    )


@router.get("/settings", response_model=SettingsResponse)
async def get_admin_settings(
    runtime: RuntimeSettingsDep,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SettingsResponse:
    return await settings_response(db, settings, runtime)


@router.put(
    "/settings",
    response_model=SettingsResponse,
    dependencies=[Depends(require_same_origin), Depends(admin_rate_limit)],
)
async def put_admin_settings(
    payload: RuntimeSettings,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> SettingsResponse:
    await db.commit()
    await db.execute(text("BEGIN IMMEDIATE"))
    stored = await load_runtime_settings(db)
    payload = payload.model_copy(
        update={field: getattr(stored, field) for field in settings.locked_discovery_fields}
    )
    effective = settings.resolve_runtime(payload)
    providers = await db.scalars(
        select(LinkedAccount.provider).where(LinkedAccount.user_id == _admin.user.id)
    )
    if not any(
        provider != "trakt" and sign_in_offered(settings, effective, provider)
        for provider in providers
    ):
        raise HTTPException(
            status_code=409, detail="Keep at least one of your linked sign-in methods"
        )
    saved = await save_runtime_settings(db, payload)
    await db.commit()
    return await settings_response(db, settings, settings.resolve_runtime(saved))


@router.get("/regions", response_model=RegionsResponse)
async def get_regions(
    catalog: CatalogDep,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
) -> RegionsResponse:
    return RegionsResponse(regions=await catalog.regions())


@router.get("/languages", response_model=LanguagesResponse)
async def get_languages(
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    catalog: CatalogDep,
) -> LanguagesResponse:
    return LanguagesResponse(languages=await catalog.languages())


@router.get("/services", response_model=ServicesResponse)
async def get_services(
    catalog: CatalogDep,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    region: Annotated[str, Query(min_length=2, max_length=2, pattern=r"^[A-Za-z]{2}$")],
) -> ServicesResponse:
    normalized = region.upper()
    return ServicesResponse(region=normalized, services=await catalog.services(normalized))


@router.post(
    "/connection-test",
    response_model=ConnectionTestResponse,
    dependencies=[Depends(require_same_origin), Depends(admin_rate_limit)],
)
async def test_connection(
    payload: ConnectionTestRequest,
    request: Request,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    settings: Annotated[Settings, Depends(get_settings)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConnectionTestResponse:
    if payload.target is ConnectionTarget.SEERR:
        await request.app.state.seerr_settings_cache.invalidate(SEERR_LOGIN_SUPPORT_KEY)
    try:
        if payload.target is ConnectionTarget.TMDB:
            key = settings.tmdb_api_key
            if key is None:
                raise CatalogNotConfigured
            client = TmdbClient(
                request.app.state.http,
                key.get_secret_value(),
                request.app.state.catalog_cache,
            )
            await client.probe()
        elif payload.target is ConnectionTarget.SEERR:
            if (
                not settings.seerr_configured
                or settings.seerr_internal_url is None
                or settings.seerr_api_key is None
            ):
                return _failed(payload.target)
            seerr = SeerrClient(
                request.app.state.http,
                settings.seerr_internal_url,
                settings.seerr_api_key.get_secret_value(),
            )
            await seerr.probe()
        elif payload.target is ConnectionTarget.PLEX:
            if not provider_configured(settings, "plex"):
                return _failed(payload.target, "Plex is not configured")
            link = await get_link(db, _admin.user.id, "plex")
            if link is None or link.credential_enc is None:
                return _failed(payload.target, "Link Plex on your Account page to test it")
            assert settings.tasterr_secret_key is not None
            secret = settings.tasterr_secret_key.get_secret_value()
            token = decrypt_token(secret, link.credential_enc)
            plex = build_plex_media(request, settings, secret)
            async with asyncio.timeout(10):
                await plex.account(token)
                discovery = await plex.discover_servers(token)
            if not discovery.servers:
                return _failed(payload.target, "Plex.tv works, but no Plex server was reachable")
        else:
            jellyfin = build_jellyfin(request, settings)
            if jellyfin is None:
                return _failed(payload.target, "Jellyfin is not configured")
            link = await get_link(db, _admin.user.id, "jellyfin")
            if link is None:
                await jellyfin.public_info()
                return _failed(
                    payload.target,
                    "Jellyfin is reachable. Link your Jellyfin account to verify the API key",
                )
            await jellyfin.user(link.external_id)
    except (CatalogNotConfigured, UpstreamError, InvalidToken, TimeoutError):
        return _failed(payload.target)
    return ConnectionTestResponse(
        target=payload.target,
        ok=True,
        detail="Connection successful",
    )


def _failed(target: ConnectionTarget, detail: str = "Connection failed") -> ConnectionTestResponse:
    return ConnectionTestResponse(target=target, ok=False, detail=detail)

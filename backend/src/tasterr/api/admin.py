"""Admin-only runtime settings, catalog choices, and configured probes (M5)."""

from enum import StrEnum
from typing import Annotated, cast

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.catalog import CatalogDep
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.auth.deps import (
    AuthedSession,
    get_db,
    require_admin,
    require_same_origin,
)
from tasterr.auth.ratelimit import TokenBucket
from tasterr.catalog.models import RegionOption, ServiceOption
from tasterr.clients.errors import UpstreamError
from tasterr.clients.seerr import SeerrClient
from tasterr.clients.tmdb import CatalogNotConfigured, TmdbClient
from tasterr.db.runtime_settings import save_runtime_settings
from tasterr.runtime_settings import (
    RailTypeDescriptor,
    RuntimeSettings,
    rail_type_descriptors,
)
from tasterr.settings import Settings, get_settings

router = APIRouter()


class SettingsResponse(BaseModel):
    settings: RuntimeSettings
    rail_types: list[RailTypeDescriptor]


class RegionsResponse(BaseModel):
    regions: list[RegionOption]


class ServicesResponse(BaseModel):
    region: str
    services: list[ServiceOption]


class ConnectionTarget(StrEnum):
    TMDB = "tmdb"
    SEERR = "seerr"


class ConnectionTestRequest(BaseModel):
    target: ConnectionTarget


class ConnectionTestResponse(BaseModel):
    target: ConnectionTarget
    ok: bool
    detail: str


def admin_rate_limit(
    request: Request,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
) -> None:
    """Spend mutation capacity only after the caller proves admin authority."""
    bucket = cast("TokenBucket", request.app.state.admin_bucket)
    key = request.client.host if request.client else "unknown"
    if not bucket.allow(key):
        raise HTTPException(status_code=429, detail="Too many admin actions")


@router.get("/settings", response_model=SettingsResponse)
async def get_admin_settings(
    runtime: RuntimeSettingsDep,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
) -> SettingsResponse:
    return SettingsResponse(settings=runtime, rail_types=rail_type_descriptors())


@router.put(
    "/settings",
    response_model=SettingsResponse,
    dependencies=[Depends(require_same_origin), Depends(admin_rate_limit)],
)
async def put_admin_settings(
    payload: RuntimeSettings,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> SettingsResponse:
    saved = await save_runtime_settings(db, payload)
    await db.commit()
    return SettingsResponse(settings=saved, rail_types=rail_type_descriptors())


@router.get("/regions", response_model=RegionsResponse)
async def get_regions(
    catalog: CatalogDep,
    _admin: Annotated[AuthedSession, Depends(require_admin)],
) -> RegionsResponse:
    return RegionsResponse(regions=await catalog.regions())


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
) -> ConnectionTestResponse:
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
        else:
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
    except (CatalogNotConfigured, UpstreamError):
        return _failed(payload.target)
    return ConnectionTestResponse(
        target=payload.target,
        ok=True,
        detail="Connection successful",
    )


def _failed(target: ConnectionTarget) -> ConnectionTestResponse:
    return ConnectionTestResponse(target=target, ok=False, detail="Connection failed")

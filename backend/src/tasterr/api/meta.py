"""Meta endpoints: health (liveness + configured flags) and public config."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tasterr.auth.deps import AuthedSession, require_session
from tasterr.settings import PublicConfig, Settings, get_settings

router = APIRouter()


class HealthResponse(BaseModel):
    status: Literal["ok"]
    tmdb_configured: bool
    seerr_configured: bool


# Unauthenticated by explicit decision (design.md): liveness must work before
# login exists, and the container healthcheck depends on it. Booleans only.
@router.get("/health")
def get_health(settings: Annotated[Settings, Depends(get_settings)]) -> HealthResponse:
    return HealthResponse(
        status="ok",
        tmdb_configured=settings.tmdb_configured,
        seerr_configured=settings.seerr_configured,
    )


@router.get("/config")
def get_config(
    settings: Annotated[Settings, Depends(get_settings)],
    _authed: Annotated[AuthedSession, Depends(require_session)],
) -> PublicConfig:
    return PublicConfig.from_settings(settings)

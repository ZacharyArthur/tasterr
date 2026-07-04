"""Meta endpoints: health (liveness + configured flags)."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from tasterr.settings import Settings, get_settings

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

"""Batch availability hydration (SPEC §6). Session-gated; degrades to Unknown.

The SPA hydrates badges *after* a feed renders by posting the visible title ids
here — browsing never waits on Seerr. Availability reads use the global API key
(not user-attributed), so badges keep resolving even when a user's Seerr session
has lapsed.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from tasterr.auth.deps import AuthedSession, require_session
from tasterr.catalog.availability import Availability, AvailabilityService
from tasterr.clients.seerr import SeerrClient
from tasterr.settings import Settings, get_settings

router = APIRouter()
MAX_BATCH = 100


class AvailabilityItem(BaseModel):
    media_type: Literal["movie", "tv"]
    id: int = Field(ge=1)


class AvailabilityRequest(BaseModel):
    items: Annotated[list[AvailabilityItem], Field(max_length=MAX_BATCH)] = []


def get_availability(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> AvailabilityService:
    # Session is required first (default-deny). Unconfigured Seerr → a service with
    # no client, which yields Unknown for every title without a call.
    cache = request.app.state.seerr_cache
    if (
        not settings.seerr_configured
        or settings.seerr_internal_url is None
        or settings.seerr_api_key is None
    ):
        return AvailabilityService(None, cache)
    client = SeerrClient(
        request.app.state.http,
        settings.seerr_internal_url,
        settings.seerr_api_key.get_secret_value(),
    )
    return AvailabilityService(client, cache)


AvailabilityDep = Annotated[AvailabilityService, Depends(get_availability)]


# A read-only batch (a POST only because the id list is a body, not a query
# string): it mutates nothing, so no CSRF origin check is applied — SPEC §9 scopes
# CSRF to mutations, and session-gating + SameSite=Lax already cover this read. If
# this ever writes state (e.g. an M4 signal), it must gain require_same_origin.
@router.post("/availability")
async def post_availability(
    payload: AvailabilityRequest,
    availability: AvailabilityDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
) -> dict[str, Availability]:
    return await availability.batch((item.media_type, item.id) for item in payload.items)

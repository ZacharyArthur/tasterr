"""Request destinations (request-destination-override). Session-gated; degrades
to an empty list.

Lets the SPA offer a non-default server/quality-profile/root-folder choice when
a title's media type has more than one configured Seerr destination. A read
using the global API key (household configuration, not a per-user action) —
same posture as availability reads.
"""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Path, Request
from pydantic import BaseModel

from tasterr.auth.deps import AuthedSession, require_session
from tasterr.clients.errors import UpstreamError
from tasterr.clients.seerr import MediaType, SeerrClient, SeerrServer, SeerrServerDetail
from tasterr.recommend.signals import MAX_TMDB_ID
from tasterr.settings import Settings, get_settings

router = APIRouter()


class DestinationProfile(BaseModel):
    id: int
    name: str


class DestinationRootFolder(BaseModel):
    id: int
    path: str


class RequestDestination(BaseModel):
    server_id: int
    server_name: str
    is_default: bool
    default_profile_id: int
    default_root_folder: str
    quality_profiles: list[DestinationProfile]
    root_folders: list[DestinationRootFolder]


def get_destinations_client(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SeerrClient | None:
    # Session is required first (default-deny). Unconfigured Seerr → no client,
    # the handler returns an empty list without attempting a call.
    if (
        not settings.seerr_configured
        or settings.seerr_internal_url is None
        or settings.seerr_api_key is None
    ):
        return None
    return SeerrClient(
        request.app.state.http,
        settings.seerr_internal_url,
        settings.seerr_api_key.get_secret_value(),
    )


DestinationsClientDep = Annotated[SeerrClient | None, Depends(get_destinations_client)]


@router.get("/{media_type}/{tmdb_id}/destinations")
async def get_destinations(
    media_type: Literal["movie", "tv"],
    tmdb_id: Annotated[int, Path(ge=1, le=MAX_TMDB_ID)],
    client: DestinationsClientDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
) -> list[RequestDestination]:
    # tmdb_id only selects radarr-vs-sonarr dispatch via media_type; the id
    # itself is accepted for a consistent, validated route shape with the
    # request/title endpoints and isn't otherwise used.
    del tmdb_id
    return await list_destinations(client, media_type)


async def list_destinations(
    client: SeerrClient | None, media_type: MediaType
) -> list[RequestDestination]:
    """Shared by the destinations endpoint and the request endpoint's override
    validation (request-destination-override) — degrades to an empty list on
    any failure, never raises, so a destinations lookup never itself blocks a
    plain default-destination request."""
    if client is None:
        return []
    try:
        servers = await client.list_servers(media_type)
    except UpstreamError:
        return []
    destinations: list[RequestDestination] = []
    for server in servers:
        try:
            detail = await client.server_destinations(media_type, server.id)
        except UpstreamError:
            continue  # this one server's detail failed; still offer the rest
        destinations.append(_to_destination(server, detail))
    return destinations


def _to_destination(server: SeerrServer, detail: SeerrServerDetail) -> RequestDestination:
    return RequestDestination(
        server_id=server.id,
        server_name=server.name,
        is_default=server.is_default,
        default_profile_id=server.active_profile_id,
        default_root_folder=server.active_directory,
        quality_profiles=[DestinationProfile(id=p.id, name=p.name) for p in detail.profiles],
        root_folders=[DestinationRootFolder(id=rf.id, path=rf.path) for rf in detail.root_folders],
    )

"""Permission-scoped request options; discovery failures never block browsing."""

import asyncio
from contextlib import suppress
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
    is_4k: bool
    default_profile_id: int
    default_root_folder: str
    quality_profiles: list[DestinationProfile]
    root_folders: list[DestinationRootFolder]


class RequestOptions(BaseModel):
    available: bool = False
    can_request_standard: bool = False
    can_request_4k: bool = False
    can_request_4k_default: bool = False
    can_override: bool = False
    can_request_specials: bool = False
    can_request_partial: bool = False
    destinations: list[RequestDestination] = []


def get_destinations_client(
    _authed: Annotated[AuthedSession, Depends(require_session)],
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> SeerrClient | None:
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


@router.get("/{media_type}/{tmdb_id}/destinations", response_model=RequestOptions)
async def get_destinations(
    media_type: Literal["movie", "tv"],
    tmdb_id: Annotated[int, Path(ge=1, le=MAX_TMDB_ID)],
    client: DestinationsClientDep,
    authed: Annotated[AuthedSession, Depends(require_session)],
) -> RequestOptions:
    # The title id preserves the validated route shape; only type selects service.
    del tmdb_id
    if client is None:
        return RequestOptions()
    try:
        user = await client.user(authed.user.seerr_user_id)
        servers = await client.list_servers(media_type)
    except UpstreamError:
        return RequestOptions()
    standard = user.can_request(media_type)
    four_k_default = user.can_request(media_type, is_4k=True) and any(
        s.is_4k and s.is_default for s in servers
    )
    four_k = four_k_default or (
        user.can_request(media_type, is_4k=True)
        and user.can_override
        and any(s.is_4k for s in servers)
    )
    allowed = [s for s in servers if (four_k if s.is_4k else standard)]
    destinations = await list_destinations(client, media_type, allowed) if user.can_override else []
    specials = False
    partial = False
    if media_type == "tv":
        # A settings failure disables selection; ordinary whole-series requests survive.
        with suppress(UpstreamError):
            policy = await client.request_settings()
            partial = policy.partial_requests_enabled
            specials = partial and policy.enable_special_episodes
    return RequestOptions(
        available=True,
        can_request_standard=standard,
        can_request_4k=four_k,
        can_request_4k_default=four_k_default,
        can_override=user.can_override,
        can_request_specials=specials,
        can_request_partial=partial,
        destinations=destinations,
    )


async def list_destinations(
    client: SeerrClient, media_type: MediaType, servers: list[SeerrServer]
) -> list[RequestDestination]:
    semaphore = asyncio.Semaphore(8)

    async def one(server: SeerrServer) -> RequestDestination | None:
        async with semaphore:
            try:
                detail = await client.server_destinations(media_type, server.id)
            except UpstreamError:
                return None
        if detail.server.id != server.id or detail.server.is_4k != server.is_4k:
            return None
        return _to_destination(server, detail)

    results = await asyncio.gather(*(one(server) for server in servers))
    return [destination for destination in results if destination is not None]


def _to_destination(server: SeerrServer, detail: SeerrServerDetail) -> RequestDestination:
    return RequestDestination(
        server_id=server.id,
        server_name=server.name,
        is_default=server.is_default,
        is_4k=server.is_4k,
        default_profile_id=server.active_profile_id,
        default_root_folder=server.active_directory,
        quality_profiles=[DestinationProfile(id=p.id, name=p.name) for p in detail.profiles],
        root_folders=[DestinationRootFolder(id=rf.id, path=rf.path) for rf in detail.root_folders],
    )

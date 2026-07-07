"""Home feed and infinite-scroll rails (SPEC §6). Session-gated, read-only.

Total catalog failure surfaces as `UpstreamUnavailable` (mapped to 502 by the
app handler); a single failing rail provider degrades to fewer rails inside the
composer, never a failed request.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tasterr.api.catalog import CatalogDep
from tasterr.auth.deps import AuthedSession, require_session
from tasterr.catalog.models import HomeFeed, RailsPage
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import RailContext

router = APIRouter()


@router.get("/home")
async def get_home(
    catalog: CatalogDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
) -> HomeFeed:
    return await build_home(RailContext(catalog))


@router.get("/rails")
async def get_rails(
    catalog: CatalogDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> RailsPage:
    return await build_extra_rails(RailContext(catalog), cursor)

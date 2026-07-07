"""Multi-search (SPEC §6). Session-gated; an empty query makes no upstream call."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from tasterr.api.catalog import CatalogDep
from tasterr.auth.deps import AuthedSession, require_session
from tasterr.catalog.models import SearchResponse

router = APIRouter()


@router.get("/search")
async def search(
    catalog: CatalogDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
    q: Annotated[str, Query(max_length=100)] = "",
) -> SearchResponse:
    return SearchResponse(results=await catalog.search(q))

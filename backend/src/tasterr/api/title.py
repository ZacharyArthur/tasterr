"""Title detail (SPEC §6). Session-gated; availability/requests are M3."""

from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path

from tasterr.api.catalog import CatalogDep
from tasterr.auth.deps import AuthedSession, require_session
from tasterr.catalog.models import MediaDetail
from tasterr.clients.errors import UpstreamRejected

router = APIRouter()


@router.get("/title/{media_type}/{tmdb_id}")
async def get_title(
    media_type: Literal["movie", "tv"],
    tmdb_id: Annotated[int, Path(ge=1)],
    catalog: CatalogDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
) -> MediaDetail:
    try:
        return await catalog.detail(media_type, tmdb_id)
    except UpstreamRejected as error:
        if error.status_code == 404:
            raise HTTPException(status_code=404, detail="Title not found") from error
        raise HTTPException(status_code=502, detail="Catalog service unavailable") from error

"""Title detail (SPEC §6). Session-gated; includes Seerr availability (M3).

Availability is resolved in parallel with the TMDB detail under a short timeout and
degrades to Unknown, so Seerr never slows or fails the detail response.
"""

import asyncio
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Path
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.availability import AvailabilityDep
from tasterr.api.catalog import CatalogDep
from tasterr.auth.deps import AuthedSession, get_db, require_session
from tasterr.catalog.models import MediaDetail, TasteFlags
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.recommend import store

router = APIRouter()


@router.get("/title/{media_type}/{tmdb_id}")
async def get_title(
    media_type: Literal["movie", "tv"],
    tmdb_id: Annotated[int, Path(ge=1)],
    catalog: CatalogDep,
    availability: AvailabilityDep,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MediaDetail:
    # Start the availability read first so it overlaps the TMDB detail fetch; it
    # never raises (degrades to Unknown internally), so only detail's errors branch.
    availability_task = asyncio.ensure_future(availability.status(media_type, tmdb_id))
    try:
        detail = await catalog.detail(media_type, tmdb_id)
    except UpstreamRejected as error:
        availability_task.cancel()
        if error.status_code == 404:
            raise HTTPException(status_code=404, detail="Title not found") from error
        raise HTTPException(status_code=502, detail="Catalog service unavailable") from error
    except UpstreamUnavailable:
        availability_task.cancel()
        raise
    # The caller's own toggle state (M4) — one indexed query, keyed by the
    # session user; never another user's signals.
    watchlisted, hidden = await store.title_toggles(db, authed.user.id, media_type, tmdb_id)
    return detail.model_copy(
        update={
            "availability": await availability_task,
            "taste": TasteFlags(watchlisted=watchlisted, hidden=hidden),
        }
    )

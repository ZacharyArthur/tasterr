"""Home feed and infinite-scroll rails (SPEC §6). Session-gated, read-only.

Total catalog failure surfaces as `UpstreamUnavailable` (mapped to 502 by the
app handler); a single failing rail provider degrades to fewer rails inside the
composer, never a failed request. The home feed is personalized (M4): the
authed user and taste service ride the rail context; `/rails` extra pages stay
non-personalized.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.availability import AvailabilityDep
from tasterr.api.catalog import CatalogDep
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.auth.deps import AuthedSession, get_db, require_session
from tasterr.catalog.models import HomeFeed, RailsPage
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import RailContext
from tasterr.recommend.service import TasteService

logger = logging.getLogger("tasterr.home")
router = APIRouter()


@router.get("/home")
async def get_home(
    catalog: CatalogDep,
    availability: AvailabilityDep,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    runtime: RuntimeSettingsDep,
) -> HomeFeed:
    taste = TasteService(db, catalog, availability)
    feed = await build_home(
        RailContext(
            catalog,
            user=authed.user,
            taste=taste,
            disabled_rail_types=frozenset(runtime.disabled_rail_types),
        )
    )
    try:
        await db.commit()  # persist vectors/profile the compose lazily materialized
    except Exception:  # derived-cache write only — the composed feed still ships
        logger.exception("home: derived-cache commit failed")
        await db.rollback()
    return feed


@router.get("/rails")
async def get_rails(
    catalog: CatalogDep,
    _authed: Annotated[AuthedSession, Depends(require_session)],
    runtime: RuntimeSettingsDep,
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> RailsPage:
    return await build_extra_rails(
        RailContext(catalog, disabled_rail_types=frozenset(runtime.disabled_rail_types)), cursor
    )

"""Home feed and infinite-scroll rails (SPEC §6). Session-gated, read-only.

Total catalog failure surfaces as `UpstreamUnavailable` (mapped to 502 by the
app handler); a single failing rail provider degrades to fewer rails inside the
composer, never a failed request. The home feed is personalized (M4): the
authed user and taste service ride the rail context; `/rails` uses the user
only to keep randomized rail order stable across their paginated requests.
"""

import logging
from typing import Annotated

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, Depends, Query, Request
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.api.availability import AvailabilityDep
from tasterr.api.catalog import CatalogDep
from tasterr.api.runtime_settings import RuntimeSettingsDep
from tasterr.api.taste import build_jellyfin, build_plex_media, schedule_history
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import AuthedSession, get_db, require_session
from tasterr.auth.login import get_link
from tasterr.catalog.models import HomeFeed, RailsPage
from tasterr.catalog.plex import PlexCatalogService
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import RailContext
from tasterr.recommend.service import TasteService
from tasterr.runtime_settings import RailType
from tasterr.settings import Settings, get_settings

logger = logging.getLogger("tasterr.home")
router = APIRouter()


@router.get("/home")
async def get_home(
    catalog: CatalogDep,
    availability: AvailabilityDep,
    authed: Annotated[AuthedSession, Depends(require_session)],
    db: Annotated[AsyncSession, Depends(get_db)],
    runtime: RuntimeSettingsDep,
    request: Request,
    settings: Annotated[Settings, Depends(get_settings)],
) -> HomeFeed:
    await schedule_history(request, settings, db, authed.user.id)
    plex: PlexCatalogService | None = None
    plex_account_token: SecretStr | None = None
    link = await get_link(db, authed.user.id, "plex") if settings.plex_configured else None
    encrypted = link.credential_enc if link else None
    secret = settings.tasterr_secret_key
    if (
        RailType.CONTINUE_WATCHING not in runtime.disabled_rail_types
        and encrypted is not None
        and secret is not None
    ):
        secret_key = secret.get_secret_value()
        try:
            plex_account_token = SecretStr(decrypt_token(secret_key, encrypted))
        except InvalidToken:
            pass
        else:
            plex = PlexCatalogService(
                build_plex_media(request, settings, secret_key),
                catalog,
                request.app.state.catalog_cache,
            )
    taste = TasteService(db, catalog, availability)
    jellyfin = None
    jellyfin_user_id = None
    if (
        settings.jellyfin_configured
        and RailType.CONTINUE_WATCHING not in runtime.disabled_rail_types
    ):
        jellyfin_link = await get_link(db, authed.user.id, "jellyfin")
        if jellyfin_link is not None:
            jellyfin = build_jellyfin(request, settings)
            jellyfin_user_id = jellyfin_link.external_id
    feed = await build_home(
        RailContext(
            catalog,
            user=authed.user,
            taste=taste,
            plex=plex,
            plex_account_token=plex_account_token,
            jellyfin=jellyfin,
            jellyfin_user_id=jellyfin_user_id,
            resume_cache=request.app.state.catalog_cache,
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
    authed: Annotated[AuthedSession, Depends(require_session)],
    runtime: RuntimeSettingsDep,
    cursor: Annotated[int, Query(ge=0)] = 0,
) -> RailsPage:
    return await build_extra_rails(
        RailContext(
            catalog,
            user=authed.user,
            disabled_rail_types=frozenset(runtime.disabled_rail_types),
        ),
        cursor,
    )

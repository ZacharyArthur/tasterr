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
from tasterr.api.taste import schedule_plex_history
from tasterr.auth.crypto import decrypt_token, plex_client_identifier
from tasterr.auth.deps import AuthedSession, get_db, require_session
from tasterr.catalog.models import HomeFeed, RailsPage
from tasterr.catalog.plex import PlexCatalogService
from tasterr.clients.plex import PlexMediaClient
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
    schedule_plex_history(
        request,
        settings,
        authed.user.id,
        authed.user.plex_history_attempted_at,
        authed.session.plex_token_enc,
    )
    plex: PlexCatalogService | None = None
    plex_account_token: SecretStr | None = None
    encrypted = authed.session.plex_token_enc
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
                PlexMediaClient(request.app.state.http, plex_client_identifier(secret_key)),
                catalog,
                request.app.state.catalog_cache,
            )
    taste = TasteService(db, catalog, availability)
    feed = await build_home(
        RailContext(
            catalog,
            user=authed.user,
            taste=taste,
            plex=plex,
            plex_account_token=plex_account_token,
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

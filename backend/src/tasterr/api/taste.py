"""Shared taste-engine wiring for endpoints.

Builds a `TasteService` from request state + settings, and hosts the
best-effort profile refresh every signal write triggers (design decision 5).
TMDB-unconfigured yields no service — signal writes still succeed, the
engine just cannot build vectors until the catalog exists.
"""

import asyncio
import logging
from typing import cast

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.service import CatalogService
from tasterr.clients.seerr import SeerrClient
from tasterr.clients.tmdb import TmdbClient
from tasterr.recommend.seed import seed_in_background
from tasterr.recommend.service import TasteService
from tasterr.settings import Settings

logger = logging.getLogger("tasterr.taste")


def build_taste(
    request: Request,
    settings: Settings,
    db: AsyncSession,
    availability: AvailabilityService | None = None,
) -> TasteService | None:
    """None when TMDB is unconfigured (the engine has no feature source)."""
    if settings.tmdb_api_key is None:
        return None
    client = TmdbClient(
        request.app.state.http,
        settings.tmdb_api_key.get_secret_value(),
        request.app.state.catalog_cache,
    )
    return TasteService(db, CatalogService(client), availability)


async def refresh_profile(
    request: Request, settings: Settings, db: AsyncSession, user_id: int
) -> None:
    """Best-effort recompute after a signal write. The profile is a cache that
    self-heals on read staleness, so a failed refresh never fails the write."""
    taste = build_taste(request, settings, db)
    if taste is None:
        return
    try:
        await taste.recompute_profile(user_id)
        await db.commit()
    except Exception:  # cache maintenance — never the request's fate
        logger.exception("taste: profile refresh failed user_id=%s", user_id)
        await db.rollback()  # repair the shared session for the caller


def build_seerr(request: Request, settings: Settings) -> SeerrClient | None:
    """None when Seerr is unconfigured — callers degrade."""
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


def schedule_seed(request: Request, settings: Settings, user_id: int, seerr_user_id: int) -> None:
    """Fire-and-forget cold-start seed at login (SPEC §8) — the login response
    never waits on it. Skipped when TMDB (no feature source) or Seerr (no
    history source) is unconfigured. The task holds its ref on app.state so it
    survives until done; single-flight lives in the seeding set."""
    if (
        settings.tmdb_api_key is None
        or not settings.seerr_configured
        or settings.seerr_internal_url is None
        or settings.seerr_api_key is None
    ):
        return
    state = request.app.state
    seerr = build_seerr(request, settings)
    if seerr is None:
        return
    tmdb_key = settings.tmdb_api_key.get_secret_value()

    def taste_factory(db: AsyncSession) -> TasteService:
        client = TmdbClient(state.http, tmdb_key, state.catalog_cache)
        return TasteService(db, CatalogService(client))

    maker = cast("async_sessionmaker[AsyncSession]", state.sessionmaker)
    seeding = cast("set[int]", state.seeding)
    task = asyncio.create_task(
        seed_in_background(maker, taste_factory, seerr, seeding, user_id, seerr_user_id)
    )
    tasks = cast("set[asyncio.Task[None]]", state.seed_tasks)
    tasks.add(task)
    task.add_done_callback(tasks.discard)

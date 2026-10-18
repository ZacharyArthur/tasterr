"""Shared taste-engine wiring for endpoints.

Builds a `TasteService` from request state + settings, and hosts the
best-effort profile refresh every signal write triggers (design decision 5).
TMDB-unconfigured yields no service — signal writes still succeed, the
engine just cannot build vectors until the catalog exists.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from cryptography.fernet import InvalidToken
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.crypto import decrypt_token, plex_client_identifier
from tasterr.auth.login import get_link
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.plex import PlexMediaClient
from tasterr.clients.seerr import SeerrClient
from tasterr.clients.tmdb import TmdbClient
from tasterr.db.io import finish_io
from tasterr.db.models import utcnow
from tasterr.db.runtime_settings import load_runtime_settings
from tasterr.recommend import store
from tasterr.recommend.seed import HISTORY_THROTTLE, reserve_seed, seed_in_background
from tasterr.recommend.service import TasteService
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings

logger = logging.getLogger("tasterr.taste")
PLEX_HISTORY_INITIAL_WINDOW = timedelta(days=365)
PLEX_HISTORY_OVERLAP = timedelta(hours=24)
PLEX_HISTORY_WRITE_BATCH = 100


def build_taste(
    request: Request,
    settings: Settings,
    db: AsyncSession,
    runtime: RuntimeSettings | None = None,
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
    resolved = runtime if runtime is not None else RuntimeSettings()
    catalog = CatalogService(
        client,
        resolved.region,
        resolved.service_ids,
        availability=availability,
        hide_library_items=resolved.hide_library_items,
        excluded_service_ids=resolved.excluded_service_ids,
    )
    return TasteService(db, catalog, availability)


async def refresh_profile(
    request: Request,
    settings: Settings,
    db: AsyncSession,
    user_id: int,
    runtime: RuntimeSettings | None = None,
) -> None:
    """Best-effort recompute after a signal write. The profile is a cache that
    self-heals on read staleness, so a failed refresh never fails the write."""
    taste = build_taste(request, settings, db, runtime)
    if taste is None:
        return
    try:
        await taste.recompute_profile(user_id)
        await db.commit()
    except Exception:  # cache maintenance — never the request's fate
        logger.exception("taste: profile refresh failed")
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


def schedule_seed(
    request: Request,
    settings: Settings,
    user_id: int,
    attempted_at: datetime | None = None,
) -> None:
    """Reserve a throttled Seerr sync without delaying sign-in or Home."""
    if (
        settings.tmdb_api_key is None
        or settings.tasterr_secret_key is None
        or (attempted_at is not None and attempted_at > utcnow() - HISTORY_THROTTLE)
        or not settings.seerr_configured
        or settings.seerr_internal_url is None
        or settings.seerr_api_key is None
    ):
        return
    state = request.app.state
    if user_id in state.plex_history_resets:
        return
    seerr = build_seerr(request, settings)
    if seerr is None:
        return
    tmdb_key = settings.tmdb_api_key.get_secret_value()

    def taste_factory(db: AsyncSession, runtime: RuntimeSettings) -> TasteService:
        client = TmdbClient(state.http, tmdb_key, state.catalog_cache)
        return TasteService(db, CatalogService(client, runtime.region, runtime.service_ids))

    maker = cast("async_sessionmaker[AsyncSession]", state.sessionmaker)
    seeding = cast("set[int]", state.seeding)
    if not reserve_seed(seeding, user_id):
        return

    async def run_seed() -> None:
        try:
            async with maker() as db:
                runtime = await finish_io(load_runtime_settings(db))

            def factory(seed_db: AsyncSession) -> TasteService:
                return taste_factory(seed_db, runtime)

            await seed_in_background(
                maker,
                factory,
                seerr,
                seeding,
                user_id,
                reserved=True,
            )
        except Exception:
            logger.error("seed: scheduling setup failed")
        finally:
            seeding.discard(user_id)

    coroutine = run_seed()
    try:
        task = asyncio.create_task(coroutine)
    except Exception:
        coroutine.close()
        seeding.discard(user_id)
        logger.error("seed: task creation failed")
        return
    tasks = cast("dict[int, asyncio.Task[None]]", state.seed_tasks)
    tasks[user_id] = task

    def release(done: asyncio.Task[None]) -> None:
        if tasks.get(user_id) is done:
            tasks.pop(user_id, None)

    task.add_done_callback(release)


def schedule_plex_history(
    request: Request,
    settings: Settings,
    user_id: int,
    attempted_at: datetime | None,
    plex_token_enc: str | None,
) -> None:
    """Schedule one bounded Plex import without delaying its request."""
    secret = settings.tasterr_secret_key
    if (
        plex_token_enc is None
        or secret is None
        or not settings.seerr_configured
        or (attempted_at is not None and attempted_at > utcnow() - HISTORY_THROTTLE)
    ):
        return
    state = request.app.state
    tasks = cast("dict[int, asyncio.Task[None]]", state.plex_history_tasks)
    resets = cast("set[int]", state.plex_history_resets)
    if user_id in tasks or user_id in resets:
        return

    maker = cast("async_sessionmaker[AsyncSession]", state.sessionmaker)
    seeding = cast("set[int]", state.seeding)
    secret_key = secret.get_secret_value()

    async def run() -> None:
        while user_id in seeding:
            await asyncio.sleep(0.05)
        plex = PlexMediaClient(
            state.http,
            plex_client_identifier(secret_key),
            max_connection_probes=settings.tasterr_plex_max_connection_probes,
        )
        history = PlexCatalogService(plex, None, cast("Cache", state.catalog_cache))
        await import_plex_history(maker, history, secret_key, plex_token_enc, user_id)

    coroutine = run()
    try:
        task = asyncio.create_task(coroutine)
    except Exception:
        coroutine.close()
        logger.error("plex history: task creation failed")
        return
    tasks[user_id] = task

    def release(done: asyncio.Task[None]) -> None:
        if tasks.get(user_id) is done:
            tasks.pop(user_id, None)

    task.add_done_callback(release)


async def cancel_plex_history(request: Request, user_id: int) -> None:
    tasks = cast("dict[int, asyncio.Task[None]]", request.app.state.plex_history_tasks)
    task = tasks.get(user_id)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if tasks.get(user_id) is task:
        tasks.pop(user_id, None)


async def import_plex_history(
    maker: "async_sessionmaker[AsyncSession]",
    history: PlexCatalogService,
    secret_key: str,
    plex_token_enc: str,
    user_id: int,
) -> None:
    """Commit the attempt, finish all reads, then write facts in small batches."""
    cutoff = utcnow()
    async with maker() as db:
        link = await get_link(db, user_id, "plex")
        if link is None:
            return
        if (
            link.sync_attempted_at is not None
            and link.sync_attempted_at > cutoff - HISTORY_THROTTLE
        ):
            return
        synced_at = link.sync_synced_at
        try:
            # Release the read lock before competing with unlink's write transaction.
            await finish_io(db.commit())
            link.sync_attempted_at = cutoff
            await finish_io(db.commit())
        except Exception:
            logger.error("plex history: attempt commit failed")
            await db.rollback()
            return

        try:
            account_token = decrypt_token(secret_key, plex_token_enc)
        except InvalidToken:
            logger.warning("plex history: session token unavailable")
            return
        start = (
            cutoff - PLEX_HISTORY_INITIAL_WINDOW
            if synced_at is None
            else synced_at - PLEX_HISTORY_OVERLAP
        )
        try:
            result = await history.history(
                account_token,
                viewed_after=_unix_seconds(start),
                viewed_before=_unix_seconds(cutoff),
            )
            for offset in range(0, len(result.watches), PLEX_HISTORY_WRITE_BATCH):
                for watch in result.watches[offset : offset + PLEX_HISTORY_WRITE_BATCH]:
                    await store.record_signal(
                        db,
                        user_id,
                        watch.media_type,
                        watch.tmdb_id,
                        "watched_plex",
                        watch.watched_at,
                    )
                await finish_io(db.commit())
            if result.complete:
                link.sync_synced_at = cutoff
                await finish_io(db.commit())
        except asyncio.CancelledError:
            await db.rollback()
            raise
        except Exception:
            logger.error("plex history: import failed")
            await db.rollback()


def _unix_seconds(value: datetime) -> int:
    return int(value.replace(tzinfo=UTC).timestamp())


async def schedule_history(
    request: Request, settings: Settings, db: AsyncSession, user_id: int
) -> None:
    if not settings.seerr_configured or settings.tasterr_secret_key is None:
        return
    seerr = await get_link(db, user_id, "seerr")
    plex = await get_link(db, user_id, "plex")
    if seerr is not None:
        schedule_seed(request, settings, user_id, seerr.sync_attempted_at)
    schedule_plex_history(
        request,
        settings,
        user_id,
        plex.sync_attempted_at if plex else None,
        plex.credential_enc if plex else None,
    )


@asynccontextmanager
async def history_guard(request: Request, user_id: int) -> AsyncGenerator[None]:
    locks = cast("dict[int, asyncio.Lock]", request.app.state.history_locks)
    lock = locks.setdefault(user_id, asyncio.Lock())
    async with lock:
        paused = cast("set[int]", request.app.state.plex_history_resets)
        paused.add(user_id)
        try:
            yield
        finally:
            paused.discard(user_id)


async def cancel_seed(request: Request, user_id: int) -> None:
    tasks = cast("dict[int, asyncio.Task[None]]", request.app.state.seed_tasks)
    task = tasks.get(user_id)
    if task is not None:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if tasks.get(user_id) is task:
            tasks.pop(user_id, None)
    request.app.state.seeding.discard(user_id)

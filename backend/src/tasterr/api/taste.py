"""Shared taste-engine wiring for endpoints.

Builds a `TasteService` from request state + settings, and hosts the
best-effort profile refresh every signal write triggers (design decision 5).
TMDB-unconfigured yields no service — signal writes still succeed, the
engine just cannot build vectors until the catalog exists.
"""

import asyncio
import logging
from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import cast

from cryptography.fernet import InvalidToken
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.crypto import decrypt_token, jellyfin_device_identifier, plex_client_identifier
from tasterr.auth.login import get_link
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.clients.plex import PlexMediaClient
from tasterr.clients.seerr import SeerrClient
from tasterr.clients.tmdb import TmdbClient
from tasterr.db.io import finish_io
from tasterr.db.models import utcnow
from tasterr.db.runtime_settings import load_runtime_settings
from tasterr.recommend import store
from tasterr.recommend.jellyfin_history import read_history
from tasterr.recommend.seed import HISTORY_THROTTLE, reserve_seed, seed_in_background
from tasterr.recommend.service import TasteService
from tasterr.recommend.signals import TasteSource
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings

logger = logging.getLogger("tasterr.taste")
WATCH_HISTORY_INITIAL_WINDOW = timedelta(days=365)
WATCH_HISTORY_OVERLAP = timedelta(hours=24)
WATCH_HISTORY_WRITE_BATCH = 100


def _start_history_task(
    tasks: dict[int, asyncio.Task[None]], user_id: int, coroutine: Coroutine[object, object, None]
) -> bool:
    try:
        task = asyncio.create_task(coroutine)
    except Exception:
        coroutine.close()
        logger.error("history: task creation failed")
        return False
    tasks[user_id] = task

    def release(done: asyncio.Task[None]) -> None:
        if tasks.get(user_id) is done:
            tasks.pop(user_id, None)

    task.add_done_callback(release)
    return True


async def _cancel_history_task(tasks: dict[int, asyncio.Task[None]], user_id: int) -> None:
    task = tasks.get(user_id)
    if task is None:
        return
    task.cancel()
    await asyncio.gather(task, return_exceptions=True)
    if tasks.get(user_id) is task:
        tasks.pop(user_id, None)


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


def build_jellyfin(request: Request, settings: Settings) -> JellyfinClient | None:
    if (
        not settings.jellyfin_configured
        or settings.jellyfin_internal_url is None
        or settings.jellyfin_api_key is None
        or settings.tasterr_secret_key is None
    ):
        return None
    return JellyfinClient(
        request.app.state.http,
        settings.jellyfin_internal_url,
        settings.jellyfin_api_key.get_secret_value(),
        jellyfin_device_identifier(settings.tasterr_secret_key.get_secret_value()),
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

    tasks = cast("dict[int, asyncio.Task[None]]", state.seed_tasks)
    if not _start_history_task(tasks, user_id, run_seed()):
        seeding.discard(user_id)


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
        or not settings.plex_configured
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
            server_id=settings.plex_server_id,
        )
        history = PlexCatalogService(plex, None, cast("Cache", state.catalog_cache))
        await import_plex_history(maker, history, secret_key, plex_token_enc, user_id)

    _start_history_task(tasks, user_id, run())


async def cancel_plex_history(request: Request, user_id: int) -> None:
    tasks = cast("dict[int, asyncio.Task[None]]", request.app.state.plex_history_tasks)
    await _cancel_history_task(tasks, user_id)


def schedule_jellyfin_history(
    request: Request, settings: Settings, user_id: int, attempted_at: datetime | None
) -> None:
    client = build_jellyfin(request, settings)
    if client is None or (attempted_at is not None and attempted_at > utcnow() - HISTORY_THROTTLE):
        return
    state = request.app.state
    tasks = cast("dict[int, asyncio.Task[None]]", state.jellyfin_history_tasks)
    if user_id in tasks or user_id in state.plex_history_resets:
        return
    maker = cast("async_sessionmaker[AsyncSession]", state.sessionmaker)

    async def run() -> None:
        while user_id in state.seeding:
            await asyncio.sleep(0.05)
        await import_jellyfin_history(maker, client, user_id)

    _start_history_task(tasks, user_id, run())


async def cancel_jellyfin_history(request: Request, user_id: int) -> None:
    tasks = cast("dict[int, asyncio.Task[None]]", request.app.state.jellyfin_history_tasks)
    await _cancel_history_task(tasks, user_id)


async def import_jellyfin_history(
    maker: "async_sessionmaker[AsyncSession]", client: JellyfinClient, user_id: int
) -> None:
    cutoff = utcnow()
    async with maker() as db:
        link = await get_link(db, user_id, "jellyfin")
        if link is None or (
            link.sync_attempted_at is not None
            and link.sync_attempted_at > cutoff - HISTORY_THROTTLE
        ):
            return
        synced_at = link.sync_synced_at
        try:
            await finish_io(db.commit())
            link.sync_attempted_at = cutoff
            await finish_io(db.commit())
            start = (
                cutoff - WATCH_HISTORY_INITIAL_WINDOW
                if synced_at is None
                else synced_at - WATCH_HISTORY_OVERLAP
            )
            result = await read_history(client, link.external_id, start, cutoff)
            watches = list(result.watches.items())
            for offset in range(0, len(watches), WATCH_HISTORY_WRITE_BATCH):
                for (media_type, tmdb_id), played in watches[
                    offset : offset + WATCH_HISTORY_WRITE_BATCH
                ]:
                    await store.record_signal(
                        db, user_id, media_type, tmdb_id, "watched_jellyfin", played
                    )
                await finish_io(db.commit())
            if result.complete:
                link.sync_synced_at = cutoff
                await finish_io(db.commit())
        except asyncio.CancelledError:
            await db.rollback()
            raise
        except Exception:
            logger.error("jellyfin history: import failed")
            await db.rollback()


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
            cutoff - WATCH_HISTORY_INITIAL_WINDOW
            if synced_at is None
            else synced_at - WATCH_HISTORY_OVERLAP
        )
        try:
            result = await history.history(
                account_token,
                viewed_after=_unix_seconds(start),
                viewed_before=_unix_seconds(cutoff),
            )
            for offset in range(0, len(result.watches), WATCH_HISTORY_WRITE_BATCH):
                for watch in result.watches[offset : offset + WATCH_HISTORY_WRITE_BATCH]:
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
    request: Request,
    settings: Settings,
    db: AsyncSession,
    user_id: int,
    *,
    source: TasteSource | None = None,
) -> None:
    if settings.tasterr_secret_key is None:
        return
    if user_id in request.app.state.plex_history_resets:
        return
    async with history_guard(request, user_id):
        seerr = await get_link(db, user_id, "seerr")
        plex = await get_link(db, user_id, "plex")
        jellyfin = await get_link(db, user_id, "jellyfin")
        excluded = await store.excluded_sources(db, user_id)
    if (
        seerr is not None
        and settings.seerr_configured
        and "seerr" not in excluded
        and source in (None, "seerr")
    ):
        schedule_seed(request, settings, user_id, seerr.sync_attempted_at)
    if (
        plex is not None
        and settings.plex_configured
        and "plex" not in excluded
        and source in (None, "plex")
    ):
        schedule_plex_history(
            request, settings, user_id, plex.sync_attempted_at, plex.credential_enc
        )
    if (
        jellyfin is not None
        and settings.jellyfin_configured
        and "jellyfin" not in excluded
        and source in (None, "jellyfin")
    ):
        schedule_jellyfin_history(request, settings, user_id, jellyfin.sync_attempted_at)


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
    await _cancel_history_task(tasks, user_id)
    request.app.state.seeding.discard(user_id)


async def cancel_source_history(request: Request, user_id: int, source: TasteSource) -> None:
    if source == "browsing":
        return
    await {"seerr": cancel_seed, "plex": cancel_plex_history, "jellyfin": cancel_jellyfin_history}[
        source
    ](request, user_id)

"""Incremental, bounded Seerr request history imported as backdated signals."""

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.clients.seerr import SeerrClient
from tasterr.db.io import finish_io
from tasterr.db.models import LinkedAccount, Signal, utcnow
from tasterr.recommend import store
from tasterr.recommend.service import TasteService

logger = logging.getLogger("tasterr.seed")
HISTORY_THROTTLE = timedelta(hours=6)


def reserve_seed(seeding: set[int], user_id: int) -> bool:
    """Synchronously reserve one user's background seed before scheduling it."""
    if user_id in seeding:
        return False
    seeding.add(user_id)
    return True


async def seed_user(
    db: AsyncSession,
    taste: TasteService,
    seerr: SeerrClient,
    user_id: int,
    seerr_user_id: int,
    since: datetime | None = None,
) -> int:
    """Import the member's request history as backdated seed signals, then
    build vectors and materialize the profile. Returns the signals actually
    committed — a failed materialization doesn't lose the count (the profile
    is a cache that self-heals on the next read). Raises on import failure —
    callers choose how to degrade."""
    history = await seerr.list_requests(seerr_user_id)
    requested = set(
        (
            await finish_io(
                db.execute(
                    select(Signal.media_type, Signal.tmdb_id).where(
                        Signal.user_id == user_id,
                        Signal.kind == "request",
                    )
                )
            )
        ).all()
    )
    written = 0
    for item in history:
        if (since is not None and item.created_at < since) or (
            item.media_type,
            item.tmdb_id,
        ) in requested:
            continue
        recorded = await store.record_signal(
            db, user_id, item.media_type, item.tmdb_id, "seed_request_history", item.created_at
        )
        if recorded:
            written += 1
    await finish_io(db.commit())
    if written:
        try:
            await taste.recompute_profile(user_id)  # pre-builds the seeded vectors
            await finish_io(db.commit())
        except Exception:  # signals are durable; the profile rebuilds on read
            logger.error("seed: profile materialization failed")
            await db.rollback()
    return written


async def seed_in_background(
    maker: "async_sessionmaker[AsyncSession]",
    taste_factory: Callable[[AsyncSession], TasteService],
    seerr: SeerrClient,
    seeding: set[int],
    user_id: int,
    *,
    reserved: bool = False,
) -> None:
    """Import under a link's throttle and watermark using a task-owned session."""
    if not reserved and not reserve_seed(seeding, user_id):
        return
    try:
        async with asyncio.timeout(30), maker() as db:
            link = await finish_io(
                db.scalar(
                    select(LinkedAccount).where(
                        LinkedAccount.user_id == user_id,
                        LinkedAccount.provider == "seerr",
                    )
                )
            )
            cutoff = utcnow()
            if link is None or (
                link.sync_attempted_at is not None
                and link.sync_attempted_at > cutoff - HISTORY_THROTTLE
            ):
                return
            since = link.sync_synced_at - timedelta(hours=24) if link.sync_synced_at else None
            # Release the read lock before competing with unlink's write transaction.
            await finish_io(db.commit())
            link.sync_attempted_at = cutoff
            await finish_io(db.commit())
            written = await seed_user(
                db, taste_factory(db), seerr, user_id, int(link.external_id), since
            )
            link.sync_synced_at = cutoff
            await finish_io(db.commit())
            logger.info("seed: imported %s signals", written)
    except Exception:  # background: degrade to unseeded, retry next login/reset
        logger.error("seed: import failed")
    finally:
        seeding.discard(user_id)

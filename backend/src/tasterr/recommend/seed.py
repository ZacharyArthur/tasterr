"""Cold-start seed: Seerr request history → backdated seed signals (SPEC §8).

Scheduled fire-and-forget after login (the response never waits) and run
inline from reset. Signals are backdated to each request's creation date so
decay prices old taste honestly. A failed import leaves the user on the
non-personalized experience — retried at the next login or reset, never
surfaced as an error.
"""

import logging
from collections.abc import Callable

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.clients.seerr import SeerrClient
from tasterr.recommend import store
from tasterr.recommend.service import TasteService

logger = logging.getLogger("tasterr.seed")


async def seed_user(
    db: AsyncSession,
    taste: TasteService,
    seerr: SeerrClient,
    user_id: int,
    seerr_user_id: int,
) -> int:
    """Import the member's request history as backdated seed signals, then
    build vectors and materialize the profile. Returns the signals actually
    committed — a failed materialization doesn't lose the count (the profile
    is a cache that self-heals on the next read). Raises on import failure —
    callers choose how to degrade."""
    history = await seerr.list_requests(seerr_user_id)
    written = 0
    for item in history:
        recorded = await store.record_signal(
            db, user_id, item.media_type, item.tmdb_id, "seed_request_history", item.created_at
        )
        if recorded:
            written += 1
    await db.commit()
    if written:
        try:
            await taste.recompute_profile(user_id)  # pre-builds the seeded vectors
            await db.commit()
        except Exception:  # signals are durable; the profile rebuilds on read
            logger.exception("seed: profile materialization failed")
            await db.rollback()
    return written


async def seed_in_background(
    maker: "async_sessionmaker[AsyncSession]",
    taste_factory: Callable[[AsyncSession], TasteService],
    seerr: SeerrClient,
    seeding: set[int],
    user_id: int,
    seerr_user_id: int,
) -> None:
    """The post-login runner: opens its own session (the request's is gone by
    the time this runs), seeds only a signal-less user, single-flights per
    user (in-process set — one replica by design), and swallows every failure
    with a log line carrying no viewing behavior."""
    if user_id in seeding:
        return
    seeding.add(user_id)
    try:
        async with maker() as db:
            if await store.has_signals(db, user_id):
                return  # returning user — nothing to seed
            written = await seed_user(db, taste_factory(db), seerr, user_id, seerr_user_id)
            logger.info("seed: imported %s signals", written)
    except Exception:  # background: degrade to unseeded, retry next login/reset
        logger.exception("seed: import failed")
    finally:
        seeding.discard(user_id)

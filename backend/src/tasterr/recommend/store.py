"""Persistence for the taste tables (signals, title_features, profiles).

The math stays in the pure sibling modules; this module owns storage
semantics — toggle idempotence, retraction, detail-open day-dedup, JSON
(de)serialization. Ordinary reads/writes are keyed by the authenticated user;
the household blend path may make a caller-authorized, bounded read across its
validated member ids, but only the final combined summaries leave the service
(privacy: signals are the household's viewing behavior).
Writes flush but never commit; the request boundary owns the transaction.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, cast

from pydantic import TypeAdapter, ValidationError
from sqlalchemy import delete, select, text, tuple_
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.db.models import Profile, Signal, TitleFeatures, utcnow
from tasterr.recommend.features import FeatureRecord
from tasterr.recommend.signals import (
    SIGNAL_WEIGHTS,
    TOGGLE_KINDS,
    UNIQUE_PER_TITLE_KINDS,
    MediaType,
    SignalKind,
    TitleKey,
)

_VECTOR = TypeAdapter(dict[str, float])


@dataclass
class StoredProfile:
    vector: dict[str, float]
    computed_at: datetime


async def record_signal(
    db: AsyncSession,
    user_id: int,
    media_type: MediaType,
    tmdb_id: int,
    kind: SignalKind,
    created_at: datetime | None = None,
) -> bool:
    """Record a signal honoring per-kind semantics; returns whether a row was
    written. Toggle/seed re-adds and same-day detail reopens are successful
    no-ops; Plex watches move their one title row only to a newer watch time.
    `created_at` backdates server imports so decay prices them honestly
    (only server imports may backdate — the detail-open dedup window derives from the
    incoming moment's calendar day, so a backdated detail_open would silently
    shift it). A written signal invalidates the materialized profile in the
    same transaction, so a failed best-effort recompute self-heals on the
    next read instead of serving a stale-but-fresh profile for 24 h."""
    moment = created_at if created_at is not None else utcnow()
    if kind in UNIQUE_PER_TITLE_KINDS:
        # The database decides (ux_signals_unique_per_title): there is no
        # check-then-insert to race, so concurrent sessions — a background
        # login-seed vs. an inline reset — cannot duplicate a title's row.
        statement = sqlite_insert(Signal).values(
            user_id=user_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            kind=kind,
            weight=SIGNAL_WEIGHTS[kind],
            created_at=moment,
        )
        if kind == "watched_plex":
            statement = statement.on_conflict_do_update(
                index_elements=[Signal.user_id, Signal.media_type, Signal.tmdb_id, Signal.kind],
                index_where=text(
                    "kind IN ('watchlist', 'not_interested', "
                    "'seed_request_history', 'watched_plex')"
                ),
                set_={
                    "weight": statement.excluded.weight,
                    "created_at": statement.excluded.created_at,
                },
                where=statement.excluded.created_at > Signal.created_at,
            )
        else:
            statement = statement.on_conflict_do_nothing(
                index_elements=[Signal.user_id, Signal.media_type, Signal.tmdb_id, Signal.kind],
                index_where=text(
                    "kind IN ('watchlist', 'not_interested', "
                    "'seed_request_history', 'watched_plex')"
                ),
            )
        result = await db.execute(statement)
        # DML through AsyncSession.execute is a CursorResult at runtime; the
        # Result[Any] annotation just doesn't know it.
        written = cast("CursorResult[Any]", result).rowcount > 0
        if written:
            await invalidate_profile(db, user_id)
        return written
    day_start = moment.replace(hour=0, minute=0, second=0, microsecond=0)
    if kind == "detail_open" and await _signal_exists(
        db, user_id, media_type, tmdb_id, kind, since=day_start
    ):
        return False
    db.add(
        Signal(
            user_id=user_id,
            tmdb_id=tmdb_id,
            media_type=media_type,
            kind=kind,
            weight=SIGNAL_WEIGHTS[kind],
            created_at=moment,
        )
    )
    await invalidate_profile(db, user_id)
    await db.flush()
    return True


async def retract_signal(
    db: AsyncSession, user_id: int, media_type: MediaType, tmdb_id: int, kind: SignalKind
) -> None:
    """Remove the user's signals of a toggle kind for one title, invalidating
    the materialized profile in the same transaction."""
    if kind not in TOGGLE_KINDS:
        raise ValueError(f"kind {kind!r} is append-only and cannot be retracted")
    await db.execute(
        delete(Signal).where(
            Signal.user_id == user_id,
            Signal.media_type == media_type,
            Signal.tmdb_id == tmdb_id,
            Signal.kind == kind,
        )
    )
    await invalidate_profile(db, user_id)


async def invalidate_profile(db: AsyncSession, user_id: int) -> None:
    """Drop the materialized profile (a pure cache) so the next read rebuilds
    it from signals — the atomic half of the recompute-on-write policy."""
    await db.execute(delete(Profile).where(Profile.user_id == user_id))


async def load_signals(db: AsyncSession, user_id: int) -> list[Signal]:
    """All of one user's signals, newest first."""
    result = await db.execute(
        select(Signal).where(Signal.user_id == user_id).order_by(Signal.created_at.desc())
    )
    return list(result.scalars().all())


async def has_signals(db: AsyncSession, user_id: int) -> bool:
    result = await db.execute(select(Signal.id).where(Signal.user_id == user_id).limit(1))
    return result.first() is not None


async def load_features(
    db: AsyncSession, keys: list[TitleKey], fresh_since: datetime
) -> dict[TitleKey, FeatureRecord]:
    """Stored feature records for `keys`, treating rows fetched before
    `fresh_since` (or unparseable ones) as missing so callers rebuild them."""
    if not keys:
        return {}
    # populate_existing: the writes below are raw upserts, so identity-mapped
    # instances from earlier in the session must be refreshed, not reused.
    result = await db.execute(
        select(TitleFeatures)
        .where(tuple_(TitleFeatures.media_type, TitleFeatures.tmdb_id).in_(list(keys)))
        .execution_options(populate_existing=True)
    )
    records: dict[TitleKey, FeatureRecord] = {}
    for row in result.scalars():
        if row.fetched_at < fresh_since:
            continue
        try:
            record = FeatureRecord.model_validate_json(row.features)
        except ValidationError:
            continue
        media: MediaType = "tv" if row.media_type == "tv" else "movie"
        records[(media, row.tmdb_id)] = record
    return records


async def save_features(
    db: AsyncSession, key: TitleKey, record: FeatureRecord, fetched_at: datetime | None = None
) -> None:
    # A real upsert (not merge): merge's select-then-insert races concurrent
    # writers of the same title — last write wins is exactly right for a cache.
    media_type, tmdb_id = key
    statement = sqlite_insert(TitleFeatures).values(
        tmdb_id=tmdb_id,
        media_type=media_type,
        features=record.model_dump_json(),
        fetched_at=fetched_at if fetched_at is not None else utcnow(),
    )
    statement = statement.on_conflict_do_update(
        index_elements=[TitleFeatures.tmdb_id, TitleFeatures.media_type],
        set_={
            "features": statement.excluded.features,
            "fetched_at": statement.excluded.fetched_at,
        },
    )
    await db.execute(statement)


async def load_profile(db: AsyncSession, user_id: int) -> StoredProfile | None:
    # A select (not db.get) with populate_existing, for the same reason as
    # load_features: upserts and invalidations bypass the identity map.
    result = await db.execute(
        select(Profile).where(Profile.user_id == user_id).execution_options(populate_existing=True)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    try:
        vector = _VECTOR.validate_json(row.vector)
    except ValidationError:
        return None
    return StoredProfile(vector=vector, computed_at=row.computed_at)


async def save_profile(db: AsyncSession, user_id: int, vector: dict[str, float]) -> None:
    serialized = _VECTOR.dump_json(vector).decode()
    statement = sqlite_insert(Profile).values(
        user_id=user_id, vector=serialized, computed_at=utcnow()
    )
    statement = statement.on_conflict_do_update(
        index_elements=[Profile.user_id],
        set_={"vector": statement.excluded.vector, "computed_at": statement.excluded.computed_at},
    )
    await db.execute(statement)


async def title_toggles(
    db: AsyncSession, user_id: int, media_type: MediaType, tmdb_id: int
) -> tuple[bool, bool]:
    """(watchlisted, hidden) for one title — the caller's own state only."""
    watchlisted = await _signal_exists(db, user_id, media_type, tmdb_id, "watchlist")
    hidden = await _signal_exists(db, user_id, media_type, tmdb_id, "not_interested")
    return watchlisted, hidden


async def delete_user_taste(db: AsyncSession, user_id: int) -> None:
    """Wipe one user's signals and profile (reset); touches nobody else."""
    await db.execute(delete(Signal).where(Signal.user_id == user_id))
    await db.execute(delete(Profile).where(Profile.user_id == user_id))


async def _signal_exists(
    db: AsyncSession,
    user_id: int,
    media_type: MediaType,
    tmdb_id: int,
    kind: SignalKind,
    since: datetime | None = None,
) -> bool:
    query = select(Signal.id).where(
        Signal.user_id == user_id,
        Signal.media_type == media_type,
        Signal.tmdb_id == tmdb_id,
        Signal.kind == kind,
    )
    if since is not None:
        query = query.where(Signal.created_at >= since)
    result = await db.execute(query.limit(1))
    return result.first() is not None

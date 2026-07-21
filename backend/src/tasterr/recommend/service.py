"""Taste engine orchestration: vectors, profile lifecycle, candidate pools.

The one face `api/` and `rails/` see. Pure math lives in the sibling modules,
persistence in store.py, and every operation is bound to one user id. Methods
raise upstream/storage errors; the rail seam degrades them to an omitted rail
(SPEC: personalization never blocks browsing).
"""

import asyncio
import logging
from contextlib import suppress
from datetime import timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.models import MediaSummary
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError
from tasterr.db.models import Signal, utcnow
from tasterr.recommend import store
from tasterr.recommend.explain import Explanation, explain
from tasterr.recommend.features import FeatureRecord, build_record
from tasterr.recommend.profile import SignalInput, compute_profile
from tasterr.recommend.scorer import Candidate, engaged_titles, hidden_titles, rank
from tasterr.recommend.signals import STRONG_POSITIVE_KINDS, MediaType, TitleKey

logger = logging.getLogger("tasterr.recommend")

VECTOR_MAX_AGE = timedelta(days=30)
PROFILE_MAX_AGE = timedelta(hours=24)
BUILD_CONCURRENCY = 8
CANDIDATE_CAP = 150
RAIL_SIZE = 20
TOP_SOURCE_TITLES = 3  # strong-positive titles whose recs/similar seed the pool
TOP_GENRES = 2
# In-library statuses that earn the availability boost ("watch tonight").
_BOOST_STATUSES = ("available", "partial")


class TasteService:
    def __init__(
        self,
        db: AsyncSession,
        catalog: CatalogService,
        availability: AvailabilityService | None = None,
    ) -> None:
        self._db = db
        self._catalog = catalog
        self._availability = availability

    async def rollback(self) -> None:
        """Restore the shared session after a degraded operation, so a failed
        flush can't poison the request's later commits (rails degrade seam)."""
        await self._db.rollback()

    # ── vectors ────────────────────────────────────────────────────────────

    async def ensure_vectors(self, keys: list[TitleKey]) -> dict[TitleKey, FeatureRecord]:
        """Stored-fresh vectors for `keys`, building (and persisting) missing
        or stale ones from title facts. A title whose build fails is skipped —
        it scores next time."""
        unique = list(dict.fromkeys(keys))
        records = await store.load_features(self._db, unique, utcnow() - VECTOR_MAX_AGE)
        records = {
            key: record
            for key, record in records.items()
            if record.watch_region == self._catalog.region
        }
        missing = [key for key in unique if key not in records]
        if not missing:
            return records
        semaphore = asyncio.Semaphore(BUILD_CONCURRENCY)

        async def build(key: TitleKey) -> tuple[TitleKey, FeatureRecord] | None:
            media_type, tmdb_id = key
            async with semaphore:
                try:
                    facts = await self._catalog.title_facts(media_type, tmdb_id)
                    return key, build_record(facts)
                except UpstreamError as error:
                    logger.warning(
                        "recommend: vector build skipped for %s:%s: %s",
                        media_type,
                        tmdb_id,
                        error,
                    )
                    return None
                except Exception:  # per-candidate: one bad title never drops the batch
                    logger.exception(
                        "recommend: vector build failed for %s:%s", media_type, tmdb_id
                    )
                    return None

        built = await asyncio.gather(*(build(key) for key in missing))
        for pair in built:
            if pair is None:
                continue
            key, record = pair
            await store.save_features(self._db, key, record)
            records[key] = record
        return records

    # ── profile lifecycle ──────────────────────────────────────────────────

    async def profile_vector(self, user_id: int) -> dict[str, float]:
        """The user's profile, recomputed when missing or stale (>24 h) so it
        keeps aging even without new signals."""
        stored = await store.load_profile(self._db, user_id)
        if stored is not None and stored.computed_at >= utcnow() - PROFILE_MAX_AGE:
            return stored.vector
        return await self.recompute_profile(user_id)

    async def recompute_profile(self, user_id: int) -> dict[str, float]:
        signals = await store.load_signals(self._db, user_id)
        if not signals:
            return {}
        keys = [_key(signal) for signal in signals]
        vectors = await self.ensure_vectors(keys)
        vector = compute_profile(
            [SignalInput(_key(s), s.weight, s.created_at) for s in signals],
            {key: record.vector for key, record in vectors.items()},
            utcnow(),
        )
        await store.save_profile(self._db, user_id, vector)
        return vector

    # ── rails ──────────────────────────────────────────────────────────────

    async def recommended_for_you(self, user_id: int) -> list[MediaSummary]:
        profile = await self.profile_vector(user_id)
        if not profile:
            return []
        signals = await store.load_signals(self._db, user_id)
        kinds = [(_key(s), _kind(s)) for s in signals]
        hidden = hidden_titles(kinds)
        # Hidden and already-engaged titles never *surface*; engaged titles
        # still *source* the pool (their recs are the recommendations).
        pool = await self._candidate_pool(profile, signals, hidden, hidden | engaged_titles(kinds))
        if not pool:
            return []
        candidates = await self._to_candidates(list(pool))
        ranked = rank(profile, candidates, RAIL_SIZE)
        return [pool[candidate.key] for candidate in ranked]

    async def more_like(self, user_id: int) -> tuple[str, list[MediaSummary]] | None:
        """Candidates related to the user's most recent strong-positive title,
        re-ranked by their profile. Returns (source title, items)."""
        profile = await self.profile_vector(user_id)
        if not profile:
            return None
        signals = await store.load_signals(self._db, user_id)
        hidden = hidden_titles((_key(s), _kind(s)) for s in signals)
        source = next(
            (s for s in signals if _kind(s) in STRONG_POSITIVE_KINDS and _key(s) not in hidden),
            None,
        )
        if source is None:
            return None
        detail = await self._catalog.detail(*_key(source))
        pool: dict[TitleKey, MediaSummary] = {}
        for summary in detail.recommendations + detail.similar:
            key: TitleKey = (summary.media_type, summary.id)
            if key == _key(source) or key in hidden or key in pool:
                continue
            pool[key] = summary
        if not pool:
            return None
        candidates = await self._to_candidates(list(pool))
        ranked = rank(profile, candidates, RAIL_SIZE)
        return detail.title, [pool[candidate.key] for candidate in ranked]

    async def my_list(self, user_id: int) -> list[MediaSummary]:
        """The user's active watchlist, newest first, minus anything they've
        hidden (not_interested excludes a title from *every* personalized
        rail); titles that fail to resolve are skipped, never the rail."""
        signals = await store.load_signals(self._db, user_id)
        hidden = hidden_titles((_key(s), _kind(s)) for s in signals)
        keys: list[TitleKey] = list(
            dict.fromkeys(
                _key(s) for s in signals if _kind(s) == "watchlist" and _key(s) not in hidden
            )
        )[:RAIL_SIZE]
        items: list[MediaSummary] = []
        for media_type, tmdb_id in keys:
            try:
                detail = await self._catalog.detail(media_type, tmdb_id)
            except UpstreamError:
                continue
            items.append(_to_summary(detail))
        return items

    # ── explain ────────────────────────────────────────────────────────────

    async def explain_title(self, user_id: int, media_type: MediaType, tmdb_id: int) -> Explanation:
        profile = await self.profile_vector(user_id)
        if not profile:
            return Explanation(personalized=False, reasons=[])
        vectors = await self.ensure_vectors([(media_type, tmdb_id)])
        record = vectors.get((media_type, tmdb_id))
        if record is None:
            return Explanation(personalized=False, reasons=[])
        return explain(profile, record.vector)

    # ── internals ──────────────────────────────────────────────────────────

    async def _candidate_pool(
        self,
        profile: dict[str, float],
        signals: list[Signal],
        hidden: set[TitleKey],
        excluded: set[TitleKey],
    ) -> dict[TitleKey, MediaSummary]:
        """Recs+similar for recent strong titles + top-genre discover +
        trending — all already-cached TMDB surfaces — capped, exclusions
        applied. Each source degrades independently."""
        sources: list[list[MediaSummary]] = []
        for key in self._source_titles(signals, hidden):
            try:
                detail = await self._catalog.detail(*key)
            except UpstreamError:
                continue
            sources.append(detail.recommendations + detail.similar)
        for genre_id in await self._top_genre_ids(profile):
            try:
                sources.append(await self._catalog.discover("movie", genres=[genre_id]))
            except UpstreamError:
                continue
        with suppress(UpstreamError):
            sources.append(await self._catalog.trending())
        pool: dict[TitleKey, MediaSummary] = {}
        for summaries in sources:
            for summary in summaries:
                key: TitleKey = (summary.media_type, summary.id)
                if key in excluded or key in pool:
                    continue
                pool[key] = summary
                if len(pool) >= CANDIDATE_CAP:
                    return pool
        return pool

    def _source_titles(self, signals: list[Signal], hidden: set[TitleKey]) -> list[TitleKey]:
        keys: list[TitleKey] = []
        for signal in signals:  # newest first per store.load_signals
            key = _key(signal)
            if _kind(signal) not in STRONG_POSITIVE_KINDS or key in hidden or key in keys:
                continue
            keys.append(key)
            if len(keys) >= TOP_SOURCE_TITLES:
                break
        return keys

    async def _top_genre_ids(self, profile: dict[str, float]) -> list[int]:
        labels = [
            dim.removeprefix("genre:")
            for dim, weight in sorted(profile.items(), key=lambda kv: kv[1], reverse=True)
            if dim.startswith("genre:") and weight > 0.0
        ][:TOP_GENRES]
        if not labels:
            return []
        try:
            genre_map = await self._catalog.genre_map("movie")
        except UpstreamError:
            return []
        by_lower = {name.lower(): genre_id for name, genre_id in genre_map.items()}
        return [by_lower[label] for label in labels if label in by_lower]

    async def _to_candidates(self, keys: list[TitleKey]) -> list[Candidate]:
        records = await self.ensure_vectors(keys)
        available = await self._in_library(list(records))
        selected = set(self._catalog.selected_service_ids)
        return [
            Candidate(
                key=key,
                record=record,
                available=key in available
                or (
                    record.watch_region == self._catalog.region
                    and bool(selected.intersection(record.flatrate_provider_ids))
                ),
            )
            for key, record in records.items()
        ]

    async def _in_library(self, keys: list[TitleKey]) -> set[TitleKey]:
        """Titles earning the availability boost; Seerr unconfigured/down
        degrades to no boost, never an error."""
        if self._availability is None or not keys:
            return set()
        statuses = await self._availability.batch(keys)
        return {
            (media_type, tmdb_id)
            for media_type, tmdb_id in keys
            if statuses.get(f"{media_type}:{tmdb_id}") is not None
            and statuses[f"{media_type}:{tmdb_id}"].status in _BOOST_STATUSES
        }


def _key(signal: Signal) -> TitleKey:
    media: MediaType = "tv" if signal.media_type == "tv" else "movie"
    return (media, signal.tmdb_id)


def _kind(signal: Signal) -> str:
    return signal.kind


def _to_summary(detail: MediaSummary) -> MediaSummary:
    return MediaSummary(
        id=detail.id,
        media_type=detail.media_type,
        title=detail.title,
        overview=detail.overview,
        poster_path=detail.poster_path,
        backdrop_path=detail.backdrop_path,
        year=detail.year,
        vote_average=detail.vote_average,
    )

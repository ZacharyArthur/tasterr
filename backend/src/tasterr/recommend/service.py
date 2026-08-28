"""Taste engine orchestration: vectors, profile lifecycle, candidate pools.

The one face `api/` and `rails/` see. Pure math lives in the sibling modules,
persistence in store.py, and every operation is bound to one user id. Methods
raise upstream/storage errors; the rail seam degrades them to an omitted rail
(SPEC: personalization never blocks browsing).
"""

import asyncio
import logging
from collections.abc import Awaitable
from contextlib import suppress
from datetime import date, timedelta
from random import Random

from sqlalchemy.ext.asyncio import AsyncSession

from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.models import MediaSummary
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError
from tasterr.db.models import Signal, utcnow
from tasterr.recommend import store
from tasterr.recommend.explain import Explanation, explain
from tasterr.recommend.features import FeatureRecord, build_record
from tasterr.recommend.profile import SignalInput, blend_profiles, compute_profile
from tasterr.recommend.scorer import (
    Candidate,
    engaged_titles,
    hidden_titles,
    rank,
    rank_exploration,
)
from tasterr.recommend.signals import STRONG_POSITIVE_KINDS, MediaType, TitleKey

logger = logging.getLogger("tasterr.recommend")

VECTOR_MAX_AGE = timedelta(days=30)
PROFILE_MAX_AGE = timedelta(hours=24)
BUILD_CONCURRENCY = 8
CANDIDATE_CAP = 150
RAIL_SIZE = 20
MIN_HOUSEHOLD_MEMBERS = 2
MAX_HOUSEHOLD_MEMBERS = 6
EXPLORATION_MIN_VOTES: dict[MediaType, int] = {"movie": 50, "tv": 30}
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
                except UpstreamError:
                    logger.warning("recommend: vector build skipped")
                    return None
                except Exception:  # per-candidate: one bad title never drops the batch
                    logger.exception("recommend: vector build failed")
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

    async def more_like(self, user_id: int) -> tuple[str, bool, list[MediaSummary]] | None:
        """Candidates related to the user's most recent strong-positive title,
        re-ranked by their profile. Returns (source title, is Plex watch, items)."""
        profile = await self.profile_vector(user_id)
        if not profile:
            return None
        signals = await store.load_signals(self._db, user_id)
        hidden = hidden_titles((_key(s), _kind(s)) for s in signals)
        source_keys = self._source_titles(signals, hidden)
        Random(f"more-like:{user_id}:{date.today().isoformat()}").shuffle(source_keys)
        for source_key in source_keys:
            source = next(
                signal
                for signal in signals
                if _key(signal) == source_key and _kind(signal) in STRONG_POSITIVE_KINDS
            )
            try:
                detail = await self._catalog.detail(*source_key)
            except UpstreamError:
                continue
            pool: dict[TitleKey, MediaSummary] = {}
            for summary in detail.recommendations + detail.similar:
                key: TitleKey = (summary.media_type, summary.id)
                if key == source_key or key in hidden or key in pool:
                    continue
                pool[key] = summary
            candidates = await self._to_candidates(list(pool))
            ranked = rank(profile, candidates, RAIL_SIZE)
            items = [pool[candidate.key] for candidate in ranked]
            if items:
                return detail.title, _kind(source) == "watched_plex", items
        return None

    async def unexpected_picks(self, user_id: int) -> list[MediaSummary]:
        profile = await self.profile_vector(user_id)
        if not profile:
            return []
        signals = await store.load_signals(self._db, user_id)
        kinds = [(_key(signal), _kind(signal)) for signal in signals]
        pool = await self._exploration_pool(profile, hidden_titles(kinds) | engaged_titles(kinds))
        candidates = await self._to_candidates(list(pool))
        return [
            pool[candidate.key] for candidate in rank_exploration(profile, candidates, RAIL_SIZE)
        ]

    async def household_blend(self, user_ids: list[int]) -> list[MediaSummary]:
        if not MIN_HOUSEHOLD_MEMBERS <= len(user_ids) <= MAX_HOUSEHOLD_MEMBERS or len(
            user_ids
        ) != len(set(user_ids)):
            raise ValueError("invalid household audience")
        members: list[tuple[dict[str, float], list[Signal], set[TitleKey]]] = []
        vetoed: set[TitleKey] = set()
        for user_id in sorted(user_ids):
            profile = await self.profile_vector(user_id)
            if not profile:
                raise ValueError("household profile unavailable")
            signals = await store.load_signals(self._db, user_id)
            kinds = [(_key(signal), _kind(signal)) for signal in signals]
            hidden = hidden_titles(kinds)
            vetoed.update(hidden | engaged_titles(kinds))
            members.append((profile, signals, hidden))

        profile = blend_profiles(member_profile for member_profile, _, _ in members)
        if not profile:
            raise ValueError("household profile unavailable")
        pool: dict[TitleKey, MediaSummary] = {}
        for member_profile, signals, hidden in members:
            member_pool = await self._candidate_pool(
                member_profile,
                signals,
                hidden,
                vetoed | set(pool),
                limit=CANDIDATE_CAP - len(pool),
            )
            pool.update(member_pool)
            if len(pool) >= CANDIDATE_CAP:
                break
        candidates = await self._to_candidates(list(pool))
        return [pool[candidate.key] for candidate in rank(profile, candidates, RAIL_SIZE)]

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
        *,
        limit: int | None = None,
    ) -> dict[TitleKey, MediaSummary]:
        """Recs+similar for recent strong titles + top-genre discover +
        trending — all already-cached TMDB surfaces — capped, exclusions
        applied. Each source degrades independently."""
        cap = CANDIDATE_CAP if limit is None else max(0, limit)
        if cap == 0:
            return {}
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
                if len(pool) >= cap:
                    return pool
        return pool

    async def _exploration_pool(
        self, profile: dict[str, float], excluded: set[TitleKey]
    ) -> dict[TitleKey, MediaSummary]:
        pool: dict[TitleKey, MediaSummary] = {}

        async def add(source: Awaitable[list[MediaSummary]]) -> bool:
            try:
                summaries = await source
            except UpstreamError:
                return False
            for summary in summaries:
                key: TitleKey = (summary.media_type, summary.id)
                if key in excluded or key in pool:
                    continue
                pool[key] = summary
                if len(pool) >= CANDIDATE_CAP:
                    return True
            return False

        if await add(self._catalog.trending()):
            return pool
        for media in ("movie", "tv"):
            if await add(
                self._catalog.discover(
                    media,
                    sort_by="popularity.desc",
                    min_votes=EXPLORATION_MIN_VOTES[media],
                )
            ):
                return pool
        if await add(
            self._catalog.discover(
                "movie",
                sort_by="primary_release_date.desc",
                release_lte=date.today().isoformat(),
                min_votes=5,
            )
        ):
            return pool

        leading = {
            dimension.removeprefix("genre:")
            for dimension, weight in profile.items()
            if dimension.startswith("genre:") and weight > 0.0
        }
        for media in ("movie", "tv"):
            try:
                genres = await self._catalog.genre_map(media)
            except UpstreamError:
                continue
            for name, genre_id in genres.items():
                if name.lower() in leading:
                    continue
                if await add(
                    self._catalog.discover(
                        media,
                        genres=[genre_id],
                        min_votes=EXPLORATION_MIN_VOTES[media],
                    )
                ):
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

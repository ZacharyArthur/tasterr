"""Transient, per-user Continue Watching candidates and presentation cache."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from tasterr.cache import Cache, CacheOpts
from tasterr.catalog.models import MediaSummary, MediaType
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError

CONTINUE_CACHE_OPTS = CacheOpts(ttl=300, stale=0)
CONTINUE_RESOLUTION_MAX = 20
CONTINUE_WATCHING_DEADLINE_SECONDS = 10.0
TMDB_RESOLUTION_DEADLINE_SECONDS = 10.0


def continue_watching_key(user_id: int) -> str:
    return f"continue-watching:user:{user_id}"


@dataclass(frozen=True)
class ResumeCandidate:
    media_type: MediaType
    tmdb_id: int
    timestamp: float
    source_rank: tuple[int, int]
    progress_percent: int | None = None
    context: str | None = None


def merge(items: list[ResumeCandidate]) -> list[ResumeCandidate]:
    merged: dict[tuple[MediaType, int], ResumeCandidate] = {}
    for item in items:
        key = (item.media_type, item.tmdb_id)
        current = merged.get(key)
        if current is None or (-item.timestamp, item.progress_percent is None, item.source_rank) < (
            -current.timestamp,
            current.progress_percent is None,
            current.source_rank,
        ):
            merged[key] = item
    return sorted(
        merged.values(),
        key=lambda item: (-item.timestamp, item.source_rank, item.media_type, item.tmdb_id),
    )


async def resolve(
    catalog: CatalogService | None, candidates: list[ResumeCandidate]
) -> list[MediaSummary]:
    async def summary(item: ResumeCandidate) -> MediaSummary:
        if catalog is None:
            raise RuntimeError("TMDB catalog is required for Continue Watching")
        detail = await catalog.detail(item.media_type, item.tmdb_id)
        return MediaSummary(
            id=detail.id,
            media_type=detail.media_type,
            title=detail.title,
            overview=detail.overview,
            poster_path=detail.poster_path,
            backdrop_path=detail.backdrop_path,
            year=detail.year,
            vote_average=detail.vote_average,
            progress_percent=item.progress_percent,
            context=item.context,
        )

    results = await asyncio.gather(
        *(summary(item) for item in candidates[:CONTINUE_RESOLUTION_MAX]), return_exceptions=True
    )
    summaries: list[MediaSummary] = []
    for result in results:
        if isinstance(result, UpstreamError):
            continue
        if isinstance(result, BaseException):
            raise result
        summaries.append(result)
    return summaries


async def continue_watching(
    cache: Cache,
    catalog: CatalogService | None,
    user_id: int,
    sources: Sequence[Callable[[], Awaitable[list[ResumeCandidate]]]],
    *,
    deadline: float = CONTINUE_WATCHING_DEADLINE_SECONDS,
) -> list[MediaSummary]:
    async def load_source(
        source: Callable[[], Awaitable[list[ResumeCandidate]]],
    ) -> list[ResumeCandidate]:
        try:
            async with asyncio.timeout(deadline):
                return await source()
        except (TimeoutError, UpstreamError):
            return []

    async def loader() -> list[MediaSummary]:
        results = await asyncio.gather(*(load_source(source) for source in sources))
        try:
            async with asyncio.timeout(TMDB_RESOLUTION_DEADLINE_SECONDS):
                return await resolve(
                    catalog, merge([item for result in results for item in result])
                )
        except TimeoutError:
            return []

    return await cache.cached(continue_watching_key(user_id), CONTINUE_CACHE_OPTS, loader)

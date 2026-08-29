"""Bounded Plex-to-catalog mapping with no durable Plex metadata."""

import asyncio
import math
from dataclasses import dataclass
from datetime import UTC, datetime

from tasterr.cache import Cache, CacheOpts
from tasterr.catalog.models import MAX_TMDB_ID, MediaSummary, MediaType
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError, UpstreamUnavailable
from tasterr.clients.plex import (
    PlexCloudAccount,
    PlexMediaClient,
    PlexPmsItem,
    PlexServer,
    PlexServerDiscovery,
)

HISTORY_DEADLINE_SECONDS = 30.0
CONTINUE_WATCHING_DEADLINE_SECONDS = 10.0
METADATA_MAX = 500
METADATA_CONCURRENCY = 8
CONTINUE_RESOLUTION_MAX = 20
CONTINUE_CACHE_OPTS = CacheOpts(ttl=300, stale=0)


@dataclass(frozen=True)
class PlexWatch:
    media_type: MediaType
    tmdb_id: int
    watched_at: datetime


@dataclass(frozen=True)
class PlexHistoryResult:
    watches: tuple[PlexWatch, ...]
    complete: bool


@dataclass(frozen=True)
class _Candidate:
    media_type: MediaType
    tmdb_id: int
    timestamp: int
    server_index: int
    progress_percent: int | None = None
    context: str | None = None


class PlexCatalogService:
    def __init__(
        self,
        plex: PlexMediaClient,
        catalog: CatalogService | None,
        cache: Cache,
    ) -> None:
        self._plex = plex
        self._catalog = catalog
        self._cache = cache

    async def history(
        self,
        account_token: str,
        *,
        viewed_after: int,
        viewed_before: int,
    ) -> PlexHistoryResult:
        deadline = asyncio.get_running_loop().time() + HISTORY_DEADLINE_SECONDS
        try:
            async with asyncio.timeout_at(deadline):
                account, discovery = await self._account_and_discovery(account_token)
        except TimeoutError:
            raise UpstreamUnavailable("Plex history deadline exceeded") from None
        servers = list(discovery.servers)
        if not servers:
            return PlexHistoryResult((), complete=False)

        candidates, complete = await self._history_candidates(
            account,
            servers,
            viewed_after=viewed_after,
            viewed_before=viewed_before,
            deadline=deadline,
        )
        merged = _merge_candidates(candidates)
        watches = tuple(
            PlexWatch(
                media_type=item.media_type,
                tmdb_id=item.tmdb_id,
                watched_at=datetime.fromtimestamp(item.timestamp, UTC).replace(tzinfo=None),
            )
            for item in merged
        )
        return PlexHistoryResult(watches, complete=discovery.complete and complete)

    async def continue_watching(self, user_id: int, account_token: str) -> list[MediaSummary]:
        async def loader() -> list[MediaSummary]:
            try:
                async with asyncio.timeout(CONTINUE_WATCHING_DEADLINE_SECONDS):
                    return await self._load_continue_watching(account_token)
            except (TimeoutError, UpstreamError):
                return []

        return await self._cache.cached(
            f"plex:continue-watching:user:{user_id}", CONTINUE_CACHE_OPTS, loader
        )

    async def _history_candidates(
        self,
        account: PlexCloudAccount,
        servers: list[PlexServer],
        *,
        viewed_after: int,
        viewed_before: int,
        deadline: float,
    ) -> tuple[list[_Candidate], bool]:
        resolver = _MetadataResolver(self._plex)

        async def load(index: int, server: PlexServer) -> tuple[list[_Candidate], bool]:
            account_id = await self._plex.resolve_account_id(server, account)
            rows = await self._plex.history(
                server,
                account_id,
                viewed_after=viewed_after,
                viewed_before=viewed_before,
            )
            mapped = await asyncio.gather(
                *(
                    _canonical_candidate(
                        resolver,
                        index,
                        server,
                        item,
                        timestamp=item.viewed_at,
                    )
                    for item in rows
                ),
                return_exceptions=True,
            )
            candidates: list[_Candidate] = []
            complete = True
            for result in mapped:
                if isinstance(result, asyncio.CancelledError):
                    raise result
                if isinstance(result, UpstreamError):
                    complete = False
                elif isinstance(result, BaseException):
                    raise result
                elif result is not None:
                    candidates.append(result)
            return candidates, complete

        tasks = [asyncio.create_task(load(index, server)) for index, server in enumerate(servers)]
        try:
            done, pending = await asyncio.wait(tasks, timeout=_remaining(deadline))
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)

        candidates: list[_Candidate] = []
        complete = not pending
        for task in done:
            try:
                server_candidates, mapping_complete = task.result()
            except UpstreamError:
                complete = False
                continue
            candidates.extend(server_candidates)
            complete = complete and mapping_complete
        return candidates, complete and len(done) == len(servers)

    async def _load_continue_watching(self, account_token: str) -> list[MediaSummary]:
        _account, discovery = await self._account_and_discovery(account_token)
        servers = list(discovery.servers)
        if not servers:
            return []
        hub_results = await asyncio.gather(
            *(self._plex.continue_watching(server) for server in servers),
            return_exceptions=True,
        )
        resolver = _MetadataResolver(self._plex)
        pending: list[tuple[int, PlexServer, PlexPmsItem, int, int | None, str | None]] = []
        for server_index, (server, result) in enumerate(zip(servers, hub_results, strict=True)):
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, UpstreamError):
                continue
            if isinstance(result, BaseException):
                raise result
            for hub_index, item in enumerate(result):
                if item.media_type not in ("movie", "episode"):
                    continue
                progress = _progress(item)
                # Plex omits viewOffset for next-up rows; explicit null or junk is not proof.
                next_up = (
                    item.media_type == "episode" and "view_offset" not in item.model_fields_set
                )
                if progress is None and not next_up:
                    continue
                timestamp = (
                    item.last_viewed_at
                    or item.grandparent_last_viewed_at
                    or item.parent_last_viewed_at
                )
                if timestamp is None:
                    if not next_up:
                        continue
                    # Negative sentinels stay local to Continue Watching hub order.
                    timestamp = -(hub_index + 1)
                context = None
                if item.media_type == "episode":
                    context = _episode_context(item)
                    if context is None:
                        continue
                pending.append((server_index, server, item, timestamp, progress, context))
        pending.sort(key=lambda value: (-value[3], value[0]))
        selected: list[tuple[int, PlexServer, PlexPmsItem, int, int | None, str | None]] = []
        seen_raw_keys: set[tuple[int, str, str]] = set()
        for candidate in pending:
            tmdb_id = _tmdb_guid(candidate[2]) if candidate[2].media_type == "movie" else None
            rating_key = _rating_key(candidate[2].rating_key)
            key = (
                (candidate[0], "tmdb", str(tmdb_id))
                if tmdb_id is not None
                else (candidate[0], "rating", rating_key)
                if rating_key is not None
                else None
            )
            if key is not None and key in seen_raw_keys:
                continue
            if key is not None:
                seen_raw_keys.add(key)
            selected.append(candidate)
            if len(selected) == CONTINUE_RESOLUTION_MAX:
                break
        mapped = await asyncio.gather(
            *(
                _canonical_candidate(
                    resolver,
                    server_index,
                    server,
                    item,
                    timestamp=timestamp,
                    progress_percent=progress,
                    context=context,
                )
                for server_index, server, item, timestamp, progress, context in selected
            ),
            return_exceptions=True,
        )
        candidates: list[_Candidate] = []
        for result in mapped:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, UpstreamError):
                continue
            if isinstance(result, BaseException):
                raise result
            if result is not None:
                candidates.append(result)
        merged = _merge_candidates(candidates)[:CONTINUE_RESOLUTION_MAX]
        resolved = await asyncio.gather(
            *(self._resume_item(item) for item in merged), return_exceptions=True
        )
        summaries: list[MediaSummary] = []
        for result in resolved:
            if isinstance(result, asyncio.CancelledError):
                raise result
            if isinstance(result, UpstreamError):
                continue
            if isinstance(result, BaseException):
                raise result
            summaries.append(result)
        return summaries

    async def _account_and_discovery(
        self, account_token: str
    ) -> tuple[PlexCloudAccount, PlexServerDiscovery]:
        account = asyncio.create_task(self._plex.account(account_token))
        discovery = asyncio.create_task(self._plex.discover_servers(account_token))
        try:
            return await asyncio.gather(account, discovery)
        finally:
            account.cancel()
            discovery.cancel()
            await asyncio.gather(account, discovery, return_exceptions=True)

    async def _resume_item(self, item: _Candidate) -> MediaSummary:
        if self._catalog is None:
            raise RuntimeError("TMDB catalog is required for Continue Watching")
        detail = await self._catalog.detail(item.media_type, item.tmdb_id)
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


class _MetadataResolver:
    def __init__(self, plex: PlexMediaClient) -> None:
        self._plex = plex
        self._semaphore = asyncio.Semaphore(METADATA_CONCURRENCY)
        self._lock = asyncio.Lock()
        self._tasks: dict[tuple[int, str], asyncio.Task[PlexPmsItem | None]] = {}
        self._used = 0

    async def get(
        self, server_index: int, server: PlexServer, rating_key: int | str | None
    ) -> PlexPmsItem | None:
        normalized = _rating_key(rating_key)
        if normalized is None:
            return None
        key = (server_index, normalized)
        async with self._lock:
            task = self._tasks.get(key)
            if task is None:
                if self._used >= METADATA_MAX:
                    return None
                self._used += 1
                task = asyncio.create_task(self._load(server, normalized))
                self._tasks[key] = task
        return await task

    async def _load(self, server: PlexServer, rating_key: str) -> PlexPmsItem | None:
        async with self._semaphore:
            return await self._plex.metadata(server, rating_key)


async def _canonical_candidate(
    resolver: _MetadataResolver,
    server_index: int,
    server: PlexServer,
    item: PlexPmsItem,
    *,
    timestamp: int | None,
    progress_percent: int | None = None,
    context: str | None = None,
) -> _Candidate | None:
    if timestamp is None:
        return None
    if item.media_type == "movie":
        tmdb_id = _tmdb_guid(item)
        if tmdb_id is None:
            metadata = await resolver.get(server_index, server, item.rating_key)
            tmdb_id = _tmdb_guid(metadata)
        media_type: MediaType = "movie"
    elif item.media_type == "episode":
        show_key = _rating_key(item.grandparent_rating_key)
        if show_key is None:
            episode = await resolver.get(server_index, server, item.rating_key)
            show_key = _rating_key(episode.grandparent_rating_key if episode else None)
        show = await resolver.get(server_index, server, show_key)
        tmdb_id = _tmdb_guid(show)
        media_type = "tv"
    else:
        return None
    if tmdb_id is None:
        return None
    return _Candidate(
        media_type=media_type,
        tmdb_id=tmdb_id,
        timestamp=timestamp,
        server_index=server_index,
        progress_percent=progress_percent,
        context=context,
    )


def _tmdb_guid(item: PlexPmsItem | None) -> int | None:
    if item is None:
        return None
    for guid in item.guids:
        if not guid.id.startswith("tmdb://"):
            continue
        raw = guid.id.removeprefix("tmdb://")
        if raw.isdecimal() and 1 <= int(raw) <= MAX_TMDB_ID:
            return int(raw)
    return None


def _rating_key(value: int | str | None) -> str | None:
    raw = str(value) if value is not None else ""
    return raw if raw.isdecimal() and int(raw) > 0 else None


def _progress(item: PlexPmsItem) -> int | None:
    if not isinstance(item.view_offset, (int, float)) or not isinstance(
        item.duration, (int, float)
    ):
        return None
    offset = float(item.view_offset)
    duration = float(item.duration)
    if not math.isfinite(offset) or not math.isfinite(duration) or offset < 0 or duration <= 0:
        return None
    progress = math.floor(100 * offset / duration)
    return progress if 1 <= progress <= 99 else None


def _episode_context(item: PlexPmsItem) -> str | None:
    if (
        not isinstance(item.parent_index, int)
        or isinstance(item.parent_index, bool)
        or item.parent_index <= 0
        or not isinstance(item.index, int)
        or isinstance(item.index, bool)
        or item.index <= 0
    ):
        return None
    return f"S{item.parent_index} E{item.index}"


def _merge_candidates(items: list[_Candidate]) -> list[_Candidate]:
    merged: dict[tuple[MediaType, int], _Candidate] = {}
    for item in items:
        key = (item.media_type, item.tmdb_id)
        current = merged.get(key)
        if current is None or (
            item.timestamp,
            item.progress_percent is not None,
            -item.server_index,
        ) > (
            current.timestamp,
            current.progress_percent is not None,
            -current.server_index,
        ):
            merged[key] = item
    return sorted(
        merged.values(),
        key=lambda item: (-item.timestamp, item.server_index, item.media_type, item.tmdb_id),
    )


def _remaining(deadline: float) -> float:
    return max(0.0, deadline - asyncio.get_running_loop().time())

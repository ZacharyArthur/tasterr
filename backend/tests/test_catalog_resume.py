import asyncio
from dataclasses import replace
from types import SimpleNamespace
from typing import cast

import pytest
from tests.test_catalog_plex import FakeCatalog

import tasterr.cache as cache_module
import tasterr.catalog.resume as resume_module
from tasterr.cache import Cache
from tasterr.catalog.models import MediaDetail, MediaType
from tasterr.catalog.resume import (
    CONTINUE_CACHE_OPTS,
    CONTINUE_WATCHING_DEADLINE_SECONDS,
    ResumeCandidate,
    continue_watching,
    continue_watching_key,
    merge,
)
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable


@pytest.mark.parametrize(
    "plex_time,jellyfin_time,plex_progress,jellyfin_progress,winner",
    [
        (10, 11, 50, None, 1),
        (10, 10, None, 40, 1),
        (10, 10, 50, 40, 0),
        (10, 10, None, None, 0),
        (11, 10, None, 40, 0),
    ],
)
def test_merge_uses_timestamp_then_presence_of_progress_then_source(
    plex_time: int,
    jellyfin_time: int,
    plex_progress: int | None,
    jellyfin_progress: int | None,
    winner: int,
) -> None:
    plex = ResumeCandidate("movie", 1, plex_time, (0, 1), plex_progress)
    jellyfin = ResumeCandidate("movie", 1, jellyfin_time, (1, 0), jellyfin_progress)
    assert merge([jellyfin, plex]) == [[plex, jellyfin][winner]]
    assert merge([plex, jellyfin]) == [[plex, jellyfin][winner]]
    earlier_server = replace(plex, source_rank=(0, 0))
    assert merge([plex, earlier_server]) == [earlier_server]


async def test_sources_overlap_merge_before_twenty_resolutions_and_cache_per_user() -> None:
    started: set[int] = set()
    gate = asyncio.Event()
    calls = [0, 0]

    async def source(rank: int) -> list[ResumeCandidate]:
        calls[rank] += 1
        started.add(rank)
        if len(started) == 2:
            gate.set()
        await gate.wait()
        return [ResumeCandidate("movie", i, i + rank, (rank, 0), 40 + rank) for i in range(1, 31)]

    cache, catalog = Cache(), FakeCatalog()
    sources = [lambda: source(0), lambda: source(1)]
    async with asyncio.timeout(1):
        result = await continue_watching(cache, cast(CatalogService, catalog), 1, sources)
    assert len(result) == len(catalog.calls) == 20
    assert [item.id for item in result] == list(range(30, 10, -1))
    assert all(item.progress_percent == 41 for item in result)
    assert await continue_watching(cache, cast(CatalogService, catalog), 1, sources) == result
    assert calls == [1, 1]
    await continue_watching(cache, cast(CatalogService, catalog), 2, sources)
    assert calls == [2, 2]
    assert continue_watching_key(1) == "continue-watching:user:1"
    assert (CONTINUE_CACHE_OPTS.ttl, CONTINUE_CACHE_OPTS.stale) == (300, 0)
    assert CONTINUE_WATCHING_DEADLINE_SECONDS == 10


@pytest.mark.parametrize("failed_rank", [0, 1])
@pytest.mark.parametrize("timeout", [False, True])
async def test_failed_source_keeps_peer_and_has_its_own_deadline(
    failed_rank: int,
    timeout: bool,
) -> None:
    cancelled = False

    async def failed() -> list[ResumeCandidate]:
        nonlocal cancelled
        if not timeout:
            raise UpstreamUnavailable("unavailable")
        try:
            await asyncio.Event().wait()
        finally:
            cancelled = True
        return []

    async def healthy() -> list[ResumeCandidate]:
        return [ResumeCandidate("movie", 1, 100, (1 - failed_rank, 0), 40)]

    sources = [healthy, healthy]
    sources[failed_rank] = failed
    result = await continue_watching(
        Cache(),
        cast(CatalogService, FakeCatalog()),
        1,
        sources,
        deadline=0.02,
    )
    assert [item.id for item in result] == [1]
    assert cancelled == timeout


async def test_expiry_never_serves_stale_and_all_failed_is_negatively_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(monotonic=lambda: now))
    calls = 0
    fail = False

    async def source() -> list[ResumeCandidate]:
        nonlocal calls
        calls += 1
        if fail:
            raise UpstreamUnavailable("unavailable")
        return [ResumeCandidate("movie", 1, 100, (0, 0), 40)]

    cache, catalog = Cache(), cast(CatalogService, FakeCatalog())
    assert await continue_watching(cache, catalog, 1, [source, source])
    fail = True
    now += 300
    assert await continue_watching(cache, catalog, 1, [source, source]) == []
    assert calls == 4
    assert await continue_watching(cache, catalog, 1, [source, source]) == []
    assert calls == 4
    fail = False
    now += 300
    assert await continue_watching(cache, catalog, 1, [source, source])
    assert calls == 6


async def test_tmdb_deadline_cancels_resolution_caches_empty_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(monotonic=lambda: now))
    monkeypatch.setattr(resume_module, "TMDB_RESOLUTION_DEADLINE_SECONDS", 0.02)
    slow = False
    cancelled = False
    loads = 0

    class Catalog(FakeCatalog):
        async def detail(self, media_type: MediaType, tmdb_id: int) -> MediaDetail:
            nonlocal cancelled
            if slow:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled = True
            return await super().detail(media_type, tmdb_id)

    async def source() -> list[ResumeCandidate]:
        nonlocal loads
        loads += 1
        return [ResumeCandidate("movie", 1, 100, (0, 0), 40)]

    cache, catalog = Cache(), cast(CatalogService, Catalog())
    assert await continue_watching(cache, catalog, 1, [source])
    now += 300
    slow = True
    async with asyncio.timeout(1):
        assert await continue_watching(cache, catalog, 1, [source]) == []
    assert cancelled and loads == 2
    assert await continue_watching(cache, catalog, 1, [source]) == []
    assert loads == 2
    now += 300
    slow = False
    assert await continue_watching(cache, catalog, 1, [source])
    assert loads == 3


async def test_tmdb_budget_starts_after_source_budget(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(resume_module, "TMDB_RESOLUTION_DEADLINE_SECONDS", 0.05)

    class Catalog(FakeCatalog):
        async def detail(self, media_type: MediaType, tmdb_id: int) -> MediaDetail:
            await asyncio.sleep(0.01)
            return await super().detail(media_type, tmdb_id)

    async def slow_source() -> list[ResumeCandidate]:
        await asyncio.Event().wait()
        return []

    async def healthy() -> list[ResumeCandidate]:
        return [ResumeCandidate("movie", 1, 100, (0, 0), 40)]

    result = await continue_watching(
        Cache(),
        cast(CatalogService, Catalog()),
        1,
        [slow_source, healthy],
        deadline=0.02,
    )
    assert [item.id for item in result] == [1]

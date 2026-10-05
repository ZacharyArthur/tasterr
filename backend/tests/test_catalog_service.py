"""Catalog service façade over a faked TMDB client (task 2.3)."""

import asyncio
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

import tasterr.catalog.discovery as discovery_mod
from tasterr.cache import Cache
from tasterr.catalog.discovery import DiscoveryFilter
from tasterr.catalog.models import MediaSummary
from tasterr.catalog.service import CatalogService
from tasterr.clients.tmdb import (
    CatalogNotConfigured,
    TmdbClient,
    TmdbDetail,
    TmdbGenre,
    TmdbMediaPage,
    TmdbMediaResult,
    TmdbProvider,
    TmdbRegion,
)


class FakeTmdb:
    def __init__(self) -> None:
        self.calls = 0
        self.raise_not_configured = False
        self.last_region = ""
        self.last_providers: list[int] | None = None

    async def discover(
        self,
        media: str,
        *,
        region: str,
        page: int = 1,
        sort_by: str = "popularity.desc",
        genres: list[int] | None = None,
        min_votes: int | None = None,
        release_gte: str | None = None,
        release_lte: str | None = None,
        providers: list[int] | None = None,
    ) -> TmdbMediaPage:
        self.calls += 1
        self.last_region = region
        self.last_providers = providers
        return TmdbMediaPage(results=[TmdbMediaResult(id=1, title="A")])  # no media_type

    async def trending(self, media: str = "all", window: str = "day") -> TmdbMediaPage:
        self.calls += 1
        return TmdbMediaPage(results=[TmdbMediaResult(id=2, media_type="movie", title="T")])

    async def multi_search(self, query: str) -> TmdbMediaPage:
        self.calls += 1
        if self.raise_not_configured:
            raise CatalogNotConfigured
        return TmdbMediaPage(
            results=[
                TmdbMediaResult(id=3, media_type="movie", title="S"),
                TmdbMediaResult(id=4, media_type="person", name="Actor"),
            ]
        )

    async def detail(self, media: str, tmdb_id: int, region: str) -> TmdbDetail:
        self.calls += 1
        return TmdbDetail(id=tmdb_id, title="D")

    async def genres(self, media: str) -> list[TmdbGenre]:
        self.calls += 1
        return [TmdbGenre(id=28, name="Action")]

    async def regions(self) -> list[TmdbRegion]:
        self.calls += 1
        return [TmdbRegion(iso_3166_1="GB", english_name="United Kingdom")]

    async def providers(self, media: str, region: str) -> list[TmdbProvider]:
        self.calls += 1
        priority = 1 if media == "movie" else 2
        return [
            TmdbProvider(
                provider_id=8,
                provider_name="Netflix",
                logo_path="/n.png",
                display_priorities={region: priority},
            )
        ]

    async def probe(self) -> None:
        self.calls += 1


def _service(fake: FakeTmdb) -> CatalogService:
    return CatalogService(cast("TmdbClient", fake))


async def test_discover_applies_media_fallback() -> None:
    out = await _service(FakeTmdb()).discover("movie")
    assert [s.media_type for s in out] == ["movie"]
    assert out[0].title == "A"


async def test_discovery_refill_caps_pages_and_preserves_search_and_detail() -> None:
    class PagedTmdb(FakeTmdb):
        async def discover(self, media: str, *, page: int = 1, **kwargs: object) -> TmdbMediaPage:
            self.calls += 1
            return TmdbMediaPage(
                page=page, total_pages=100, results=[TmdbMediaResult(id=page, title="Title")]
            )

    fake = PagedTmdb()
    service = _service(fake)
    service.discovery_filter = DiscoveryFilter(service, None, False, [8])
    assert [item.id for item in await service.discover("movie")] == [1, 2, 3]
    # One provider-detail read and one discover call per page.
    assert fake.calls == 6
    assert (await service.search("Title"))[0].id == 3
    assert (await service.detail("movie", 1)).id == 1


async def test_discover_refills_after_confirmed_exclusions() -> None:
    class PagedTmdb(FakeTmdb):
        async def discover(self, media: str, *, page: int = 1, **kwargs: object) -> TmdbMediaPage:
            self.calls += 1
            return TmdbMediaPage(
                page=page, total_pages=2, results=[TmdbMediaResult(id=page, title="Title")]
            )

        async def detail(self, media: str, tmdb_id: int, region: str) -> TmdbDetail:
            return TmdbDetail.model_validate(
                {
                    "id": tmdb_id,
                    "title": "Title",
                    "watch/providers": {
                        "results": {
                            region: {"flatrate": [{"provider_id": 8}] if tmdb_id == 1 else []}
                        }
                    },
                }
            )

    fake = PagedTmdb()
    service = _service(fake)
    service.discovery_filter = DiscoveryFilter(service, None, False, [8])
    assert [item.id for item in await service.discover("movie")] == [2]
    assert fake.calls == 2


@pytest.mark.parametrize("empty_first", [False, True])
async def test_stalled_refill_stops_at_shared_deadline_and_retains_first_page(
    monkeypatch: pytest.MonkeyPatch,
    empty_first: bool,
) -> None:
    monkeypatch.setattr(discovery_mod, "VERIFICATION_SECONDS", 0.03)
    cancelled = asyncio.Event()
    pages: list[int] = []

    class StalledTmdb(FakeTmdb):
        async def discover(self, media: str, *, page: int = 1, **kwargs: object) -> TmdbMediaPage:
            pages.append(page)
            if page > 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return TmdbMediaPage(
                page=page,
                total_pages=10,
                results=[] if empty_first else [TmdbMediaResult(id=page, title="Title")],
            )

    service = _service(StalledTmdb())
    service.discovery_filter = DiscoveryFilter(service, None, False, [8])
    async with asyncio.timeout(0.3):
        assert [item.id for item in await service.discover("movie")] == ([] if empty_first else [1])
    assert pages == [1, 2]
    assert cancelled.is_set()
    assert service.discovery_filter.expired


async def test_empty_search_short_circuits_without_calling_client() -> None:
    fake = FakeTmdb()
    assert await _service(fake).search("   ") == []
    assert fake.calls == 0


async def test_refill_timeout_releases_real_cache_single_flight_lock(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_mod, "VERIFICATION_SECONDS", 0.03)
    cancelled = asyncio.Event()
    pages: list[int] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        if "/discover/" in request.url.path:
            page = int(request.url.params["page"])
            pages.append(page)
            if page == 2 and pages.count(2) == 1:
                try:
                    await asyncio.Event().wait()
                finally:
                    cancelled.set()
            return httpx.Response(
                200,
                json={"page": page, "total_pages": 2, "results": [{"id": page, "title": "Title"}]},
            )
        return httpx.Response(200, json={"id": 1, "title": "Title"})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = TmdbClient(http, "fixture-key", Cache())
        service = CatalogService(client)
        service.discovery_filter = DiscoveryFilter(service, None, False, [8])
        async with asyncio.timeout(1):
            assert [item.id for item in await service.discover("movie")] == [1]
            assert cancelled.is_set()
            # Same client/cache/key: no lingering page-two loader or lock.
            assert (await client.discover("movie", region="US", page=2)).results[0].id == 2
            assert (await client.discover("movie", region="US", page=2)).results[0].id == 2
        assert pages == [1, 2, 2]


async def test_search_drops_person_results() -> None:
    out = await _service(FakeTmdb()).search("q")
    assert [s.id for s in out] == [3]


async def test_not_configured_propagates() -> None:
    fake = FakeTmdb()
    fake.raise_not_configured = True
    with pytest.raises(CatalogNotConfigured):
        await _service(fake).search("q")


async def test_detail_returns_domain_detail() -> None:
    detail = await _service(FakeTmdb()).detail("movie", 42)
    assert detail.id == 42
    assert detail.media_type == "movie"


async def test_default_region() -> None:
    assert _service(FakeTmdb()).region == "US"


async def test_configured_region_and_services_flow_to_discover() -> None:
    fake = FakeTmdb()
    service = CatalogService(cast("TmdbClient", fake), "GB", [8, 337])

    await service.discover("movie")

    assert fake.last_region == "GB"
    assert fake.last_providers == [8, 337]
    assert service.selected_service_ids == (8, 337)


async def test_selected_excluded_overlap_preserves_inclusion_narrowing() -> None:
    pages: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if "/discover/" in request.url.path:
            assert request.url.params["watch_region"] == "US"
            assert request.url.params["with_watch_providers"] == "8"
            assert request.url.params["with_watch_monetization_types"] == "flatrate"
            page = int(request.url.params["page"])
            pages.append(page)
            return httpx.Response(
                200,
                json={"page": page, "total_pages": 10, "results": [{"id": page, "title": "Title"}]},
            )
        tmdb_id = int(request.url.path.rsplit("/", 1)[-1])
        return httpx.Response(
            200,
            json={
                "id": tmdb_id,
                "title": "Title",
                "watch/providers": {"results": {"US": {"flatrate": [{"provider_id": 8}]}}},
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = CatalogService(
            TmdbClient(http, "fixture-key", Cache()), "US", [8], excluded_service_ids=[8]
        )
        assert await service.discover("movie") == []
        assert pages == [1, 2, 3]
        assert service.selected_service_ids == (8,)


async def test_region_and_service_options_are_normalized() -> None:
    service = _service(FakeTmdb())

    assert (await service.regions())[0].code == "GB"
    options = await service.services("GB")
    assert [(item.provider_id, item.display_priority) for item in options] == [(8, 1)]


async def test_probe_delegates_to_client() -> None:
    fake = FakeTmdb()
    await _service(fake).probe()
    assert fake.calls == 1


@pytest.mark.parametrize("progress", [0, 100])
def test_media_summary_rejects_non_resumable_progress(progress: int) -> None:
    with pytest.raises(ValidationError):
        MediaSummary(
            id=1,
            media_type="movie",
            title="Title",
            overview="",
            poster_path=None,
            backdrop_path=None,
            year=None,
            vote_average=0,
            progress_percent=progress,
        )

"""Catalog service façade over a faked TMDB client (task 2.3)."""

from typing import cast

import pytest
from pydantic import ValidationError

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


async def test_empty_search_short_circuits_without_calling_client() -> None:
    fake = FakeTmdb()
    assert await _service(fake).search("   ") == []
    assert fake.calls == 0


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

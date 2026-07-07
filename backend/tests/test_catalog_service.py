"""Catalog service façade over a faked TMDB client (task 2.3)."""

from typing import cast

import pytest

from tasterr.catalog.service import CatalogService
from tasterr.clients.tmdb import (
    CatalogNotConfigured,
    TmdbClient,
    TmdbDetail,
    TmdbGenre,
    TmdbMediaPage,
    TmdbMediaResult,
)


class FakeTmdb:
    def __init__(self) -> None:
        self.calls = 0
        self.raise_not_configured = False

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
    ) -> TmdbMediaPage:
        self.calls += 1
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

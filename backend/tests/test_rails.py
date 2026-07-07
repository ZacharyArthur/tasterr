"""Rail providers and the composer: degrade, de-dupe, drop, paginate (tasks 3.2, 3.3)."""

from typing import cast

import pytest

from tasterr.catalog.models import Genre, MediaDetail, MediaSummary, WatchProviders
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import (
    EXTRA_PAGE_SIZE,
    HERO_SIZE,
    RailContext,
    decade_provider,
    genre_provider,
    home_providers,
    top_rated_providers,
)


def _summary(i: int) -> MediaSummary:
    return MediaSummary(
        id=i,
        media_type="movie",
        title=f"T{i}",
        overview="",
        poster_path=None,
        backdrop_path="/b.jpg",
        year=2020,
        vote_average=7.0,
    )


def _detail(i: int) -> MediaDetail:
    return MediaDetail(
        id=i,
        media_type="movie",
        title=f"T{i}",
        overview="",
        poster_path=None,
        backdrop_path="/b.jpg",
        year=2020,
        vote_average=7.0,
        tagline="",
        genres=[Genre(id=18, name="Drama")],
        runtime=100,
        release_date="2020-01-01",
        certification="PG-13",
        logo_path="/logo.png",
        trailer=None,
        cast=[],
        crew=[],
        watch=WatchProviders(),
        recommendations=[],
        similar=[],
        seasons=[],
        number_of_seasons=None,
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.region = "US"
        self.trending_items = [_summary(i) for i in range(1, 7)]
        self.fixed_discover: list[MediaSummary] | None = None
        self.genre_map_result = {"Action": 28, "Comedy": 35, "Drama": 18, "Thriller": 53}
        self.discover_calls: list[dict[str, object]] = []
        self.fail_trending = False
        self.fail_discover = False
        self.fail_genre_map = False
        self._block = 100

    async def trending(self) -> list[MediaSummary]:
        if self.fail_trending:
            raise UpstreamUnavailable("trending down")
        return list(self.trending_items)

    async def discover(
        self,
        media: str,
        *,
        page: int = 1,
        sort_by: str = "popularity.desc",
        genres: list[int] | None = None,
        min_votes: int | None = None,
        release_gte: str | None = None,
        release_lte: str | None = None,
    ) -> list[MediaSummary]:
        self.discover_calls.append(
            {
                "media": media,
                "sort_by": sort_by,
                "genres": genres,
                "min_votes": min_votes,
                "release_gte": release_gte,
                "release_lte": release_lte,
            }
        )
        if self.fail_discover:
            raise UpstreamUnavailable("discover down")
        if self.fixed_discover is not None:
            return list(self.fixed_discover)
        block = self._block
        self._block += 100
        return [_summary(block + i) for i in range(10)]

    async def genre_map(self, media: str) -> dict[str, int]:
        if self.fail_genre_map:
            raise UpstreamUnavailable("genres down")
        return dict(self.genre_map_result)

    async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
        return _detail(tmdb_id)


def _ctx(fake: FakeCatalog) -> RailContext:
    return RailContext(cast("CatalogService", fake))


# ── Providers (3.2) ──────────────────────────────────────────────────────────


def test_home_provider_ids_and_kinds() -> None:
    providers = home_providers()
    assert [p.id for p in providers] == ["trending", "popular", "recently-added"]
    assert providers[1].kind == "standard"


async def test_top_region_provider_queries_popular_movies() -> None:
    fake = FakeCatalog()
    await home_providers()[1].fetch(_ctx(fake))
    assert fake.discover_calls[-1] == {
        "media": "movie",
        "sort_by": "popularity.desc",
        "genres": None,
        "min_votes": 50,
        "release_gte": None,
        "release_lte": None,
    }


async def test_genre_provider_filters_and_labels_tv() -> None:
    provider = genre_provider(28, "Action", "tv")
    assert provider.id == "genre-tv-28"
    assert provider.title == "Action · TV"
    assert provider.kind == "genre"
    fake = FakeCatalog()
    await provider.fetch(_ctx(fake))
    assert fake.discover_calls[-1]["genres"] == [28]
    assert fake.discover_calls[-1]["min_votes"] == 30


async def test_decade_provider_bounds_release_window() -> None:
    provider = decade_provider(1990)
    assert provider.id == "decade-1990"
    assert provider.title == "1990s"
    fake = FakeCatalog()
    await provider.fetch(_ctx(fake))
    assert fake.discover_calls[-1]["release_gte"] == "1990-01-01"
    assert fake.discover_calls[-1]["release_lte"] == "1999-12-31"


def test_top_rated_provider_ids() -> None:
    assert [p.id for p in top_rated_providers()] == ["top-rated-movie", "top-rated-tv"]


# ── Composer: home (3.3) ─────────────────────────────────────────────────────


async def test_build_home_returns_hero_and_rails() -> None:
    feed = await build_home(_ctx(FakeCatalog()))
    assert len(feed.hero) == HERO_SIZE
    assert feed.hero[0].item.id == 1
    assert feed.hero[0].logo_path == "/logo.png"
    assert feed.hero[0].genres == ["Drama"]
    assert "trending" in {r.id for r in feed.rails}


async def test_one_failing_provider_still_yields_the_rest() -> None:
    fake = FakeCatalog()
    fake.fail_trending = True
    feed = await build_home(_ctx(fake))
    ids = {r.id for r in feed.rails}
    assert "trending" not in ids
    assert "popular" in ids


async def test_titles_deduped_across_rails() -> None:
    fake = FakeCatalog()
    fake.trending_items = [_summary(i) for i in range(1, 9)]  # 1..8
    fake.fixed_discover = [_summary(i) for i in range(5, 15)]  # 5..14, overlaps 5..8
    feed = await build_home(_ctx(fake))
    keys = [(it.media_type, it.id) for rail in feed.rails for it in rail.items]
    assert keys == list(dict.fromkeys(keys))  # every title appears once
    assert sum(1 for _, i in keys if i == 5) == 1


async def test_under_filled_rail_is_dropped() -> None:
    fake = FakeCatalog()
    fake.fixed_discover = [_summary(100), _summary(101), _summary(102)]  # only 3 (< min 4)
    feed = await build_home(_ctx(fake))
    ids = {r.id for r in feed.rails}
    assert "trending" in ids  # 6 items, survives
    assert "popular" not in ids  # 3 items, dropped


async def test_total_catalog_failure_raises() -> None:
    fake = FakeCatalog()
    fake.fail_trending = True
    fake.fail_discover = True
    fake.fail_genre_map = True
    with pytest.raises(UpstreamUnavailable):
        await build_home(_ctx(fake))


# ── Composer: infinite scroll (3.3) ──────────────────────────────────────────


async def test_extra_rails_first_page_has_cursor() -> None:
    page = await build_extra_rails(_ctx(FakeCatalog()), 0)
    assert page.rails[0].id == "top-rated-movie"
    assert page.next_cursor == EXTRA_PAGE_SIZE


async def test_extra_rails_paginate_then_complete() -> None:
    ctx = _ctx(FakeCatalog())
    cursor: int | None = 0
    pages = 0
    while cursor is not None:
        page = await build_extra_rails(ctx, cursor)
        cursor = page.next_cursor
        pages += 1
        assert pages < 20  # guard against a runaway cursor
    assert pages >= 2  # catalogue spans multiple pages then ends

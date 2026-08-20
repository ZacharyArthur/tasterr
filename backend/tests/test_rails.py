"""Rail providers and the composer: degrade, de-dupe, drop, paginate (tasks 3.2, 3.3)."""

from datetime import date, timedelta
from typing import cast

import pytest

from tasterr.catalog.models import (
    Genre,
    MediaDetail,
    MediaSummary,
    ServiceOption,
    WatchProviders,
)
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import (
    EXTRA_PAGE_SIZE,
    GENRE_PICKS,
    HERO_SIZE,
    HOME_GENRE_COUNT,
    RailContext,
    decade_provider,
    genre_provider,
    home_providers,
    service_provider,
    top_rated_providers,
)
from tasterr.runtime_settings import RailType


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
        external_url=f"https://www.themoviedb.org/movie/{i}",
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
        self.selected_service_ids: tuple[int, ...] = ()
        self.available_services: list[ServiceOption] = []
        self.trending_items = [_summary(i) for i in range(1, 7)]
        self.fixed_discover: list[MediaSummary] | None = None
        self.genre_map_result = {"Action": 28, "Comedy": 35, "Drama": 18, "Thriller": 53}
        self.discover_calls: list[dict[str, object]] = []
        self.fail_trending = False
        self.fail_discover = False
        self.fail_genre_map = False
        self.fail_services = False
        self.failing_service_ids: set[int] = set()
        self.genre_map_calls: list[str] = []
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
        service_ids: list[int] | None = None,
    ) -> list[MediaSummary]:
        self.discover_calls.append(
            {
                "media": media,
                "sort_by": sort_by,
                "genres": genres,
                "min_votes": min_votes,
                "release_gte": release_gte,
                "release_lte": release_lte,
                "service_ids": service_ids,
            }
        )
        if self.fail_discover or (
            service_ids is not None and bool(self.failing_service_ids.intersection(service_ids))
        ):
            raise UpstreamUnavailable("discover down")
        if self.fixed_discover is not None:
            return list(self.fixed_discover)
        block = self._block
        self._block += 100
        return [_summary(block + i) for i in range(10)]

    async def genre_map(self, media: str) -> dict[str, int]:
        self.genre_map_calls.append(media)
        if self.fail_genre_map:
            raise UpstreamUnavailable("genres down")
        return dict(self.genre_map_result)

    async def detail(self, media: str, tmdb_id: int) -> MediaDetail:
        return _detail(tmdb_id)

    async def services(self, region: str | None = None) -> list[ServiceOption]:
        if self.fail_services:
            raise UpstreamUnavailable("services down")
        return list(self.available_services)


def _ctx(fake: FakeCatalog) -> RailContext:
    return RailContext(cast("CatalogService", fake))


# ── Providers (3.2) ──────────────────────────────────────────────────────────


def test_home_provider_ids_and_kinds() -> None:
    providers = home_providers()
    assert [p.id for p in providers] == ["trending", "popular", "recently-added"]
    assert providers[1].kind == "standard"
    assert providers[2].title == "Recent Releases"


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
        "service_ids": None,
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


async def test_service_provider_queries_recent_flatrate_movies() -> None:
    service = ServiceOption(
        provider_id=8,
        name="Netflix",
        logo_path=None,
        display_priority=1,
    )
    provider = service_provider(service)
    fake = FakeCatalog()

    await provider.fetch(_ctx(fake))

    assert provider.title == "Recent Releases on Netflix"
    assert fake.discover_calls[-1] == {
        "media": "movie",
        "sort_by": "primary_release_date.desc",
        "genres": None,
        "min_votes": 3,
        "release_gte": (date.today() - timedelta(days=365)).isoformat(),
        "release_lte": date.today().isoformat(),
        "service_ids": [8],
    }


async def test_disabled_provider_is_not_fetched() -> None:
    fake = FakeCatalog()
    ctx = RailContext(
        cast("CatalogService", fake),
        disabled_rail_types=frozenset({RailType.TRENDING}),
    )

    feed = await build_home(ctx)

    assert "trending" not in {rail.id for rail in feed.rails}


async def test_all_disabled_returns_a_valid_empty_feed() -> None:
    fake = FakeCatalog()
    ctx = RailContext(
        cast("CatalogService", fake),
        disabled_rail_types=frozenset(RailType),
    )

    feed = await build_home(ctx)

    assert feed.hero == []
    assert feed.rails == []
    assert fake.discover_calls == []


async def test_selected_services_add_four_ordered_independent_rails() -> None:
    fake = FakeCatalog()
    fake.selected_service_ids = (8, 337, 9, 15, 350)
    fake.available_services = [
        ServiceOption(
            provider_id=provider_id,
            name=f"Service {provider_id}",
            logo_path=None,
            display_priority=index,
        )
        for index, provider_id in enumerate((350, 8, 337, 9, 15))
    ]

    feed = await build_home(_ctx(fake))

    service_rails = [rail for rail in feed.rails if rail.id.startswith("service-")]
    assert [rail.id for rail in service_rails] == [
        "service-8",
        "service-337",
        "service-9",
        "service-15",
    ]
    service_calls = [call for call in fake.discover_calls if call["service_ids"] is not None]
    assert [call["service_ids"] for call in service_calls] == [[8], [337], [9], [15]]


async def test_service_metadata_failure_omits_only_service_rails() -> None:
    fake = FakeCatalog()
    fake.selected_service_ids = (8, 9)
    fake.fail_services = True

    feed = await build_home(_ctx(fake))

    ids = {rail.id for rail in feed.rails}
    assert not any(rail_id.startswith("service-") for rail_id in ids)
    assert {"trending", "popular"} <= ids


async def test_one_failing_service_rail_does_not_drop_siblings() -> None:
    fake = FakeCatalog()
    fake.selected_service_ids = (8, 9)
    fake.available_services = [
        ServiceOption(
            provider_id=provider_id,
            name=f"Service {provider_id}",
            logo_path=None,
            display_priority=index,
        )
        for index, provider_id in enumerate((8, 9))
    ]
    fake.failing_service_ids = {8}

    feed = await build_home(_ctx(fake))

    ids = {rail.id for rail in feed.rails}
    assert "service-8" not in ids
    assert "service-9" in ids
    assert {"trending", "popular"} <= ids


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


async def test_curated_movie_genres_split_between_home_and_extra() -> None:
    fake = FakeCatalog()
    genre_names = (
        "Western",
        "Comedy",
        "Crime",
        "Drama",
        "Family",
        "Fantasy",
        "History",
        "Horror",
        "Music",
        "Mystery",
        "Romance",
        "Science Fiction",
        "TV Movie",
        "Thriller",
        "War",
        "Adventure",
        "Documentary",
    )
    fake.genre_map_result = {name: index for index, name in enumerate(genre_names, start=1)}
    present_curated = [name for name in GENRE_PICKS if name in fake.genre_map_result]

    home = await build_home(_ctx(fake))
    home_genres = [rail.title for rail in home.rails if rail.id.startswith("genre-movie-")]

    extra_genres: list[str] = []
    cursor: int | None = 0
    pages = 0
    while cursor is not None:
        page = await build_extra_rails(_ctx(fake), cursor)
        extra_genres.extend(rail.title for rail in page.rails if rail.id.startswith("genre-movie-"))
        cursor = page.next_cursor
        pages += 1
        assert pages < 20  # guard against a runaway cursor

    extra_curated = [name for name in extra_genres if name in GENRE_PICKS]
    combined = home_genres + extra_curated
    assert home_genres == present_curated[:HOME_GENRE_COUNT]
    assert set(home_genres).isdisjoint(extra_curated)
    assert len(combined) == len(set(combined)) == len(present_curated)
    assert set(combined) == set(present_curated)


async def test_all_disabled_extra_rails_are_terminal_without_catalog_work() -> None:
    fake = FakeCatalog()
    ctx = RailContext(
        cast("CatalogService", fake),
        disabled_rail_types=frozenset(RailType),
    )

    page = await build_extra_rails(ctx, 0)

    assert page.rails == []
    assert page.next_cursor is None
    assert fake.discover_calls == []
    assert fake.genre_map_calls == []


# ── Personalized providers (M4) ──────────────────────────────────────────────


class FakeTaste:
    """Same rail-facing surface as TasteService; the engine math is covered by
    test_recommend_service.py — these tests cover the composer plumbing."""

    def __init__(self) -> None:
        self.my_list_items: list[MediaSummary] = []
        self.recommended_items: list[MediaSummary] = []
        self.more_like_result: tuple[str, list[MediaSummary]] | None = None
        self.fail = False

    def _maybe_fail(self) -> None:
        if self.fail:
            raise RuntimeError("engine storage on fire")

    async def my_list(self, user_id: int) -> list[MediaSummary]:
        self._maybe_fail()
        return list(self.my_list_items)

    async def recommended_for_you(self, user_id: int) -> list[MediaSummary]:
        self._maybe_fail()
        return list(self.recommended_items)

    async def more_like(self, user_id: int) -> tuple[str, list[MediaSummary]] | None:
        self._maybe_fail()
        return self.more_like_result


def _personal_ctx(fake: FakeCatalog, taste: FakeTaste) -> RailContext:
    from tasterr.db.models import User
    from tasterr.recommend.service import TasteService

    user = User(id=1, seerr_user_id=1, display_name="member", auth_type="plex", is_admin=False)
    return RailContext(cast("CatalogService", fake), user=user, taste=cast("TasteService", taste))


async def test_personalized_home_orders_and_titles_rails() -> None:
    taste = FakeTaste()
    taste.my_list_items = [_summary(500)]  # a one-title list still renders
    taste.recommended_items = [_summary(600 + i) for i in range(6)]
    taste.more_like_result = ("Dune", [_summary(700 + i) for i in range(6)])

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    ids = [rail.id for rail in feed.rails]
    assert ids[:2] == ["my-list", "recommended-for-you"]
    assert ids[2] == "trending"
    assert ids[3] == "more-like"
    more_like = feed.rails[3]
    assert more_like.title == "More like Dune"  # resolved from the source title
    my_list = feed.rails[0]
    assert [item.id for item in my_list.items] == [500]


async def test_signalless_user_gets_the_plain_home() -> None:
    taste = FakeTaste()  # no signals → every personalized provider yields []

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))
    plain = await build_home(_ctx(FakeCatalog()))

    assert [rail.id for rail in feed.rails] == [rail.id for rail in plain.rails]
    assert not any(
        rail.id in ("my-list", "recommended-for-you", "more-like") for rail in feed.rails
    )


async def test_engine_failure_degrades_to_the_plain_home() -> None:
    taste = FakeTaste()
    taste.fail = True  # storage/engine errors, not upstream ones

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    ids = [rail.id for rail in feed.rails]
    assert "trending" in ids
    assert not any(rail_id in ("my-list", "recommended-for-you", "more-like") for rail_id in ids)


async def test_exclusive_providers_never_run_concurrently() -> None:
    """Deterministic pin of the serialization invariant (round-2 blocker):
    exclusive providers share the request's AsyncSession, so the composer must
    run them one at a time. The probes raise on overlap — reverting
    `_fetch_all` to a plain gather fails this test immediately."""
    import asyncio

    # Deliberate seam test of the composer's serialization guarantee.
    from tasterr.rails.composer import _compose_rails  # pyright: ignore[reportPrivateUsage]
    from tasterr.rails.registry import RailProvider

    active = 0

    def probe(provider_id: str, base: int) -> RailProvider:
        async def fetch(_: RailContext) -> list[MediaSummary]:
            nonlocal active
            active += 1
            overlap = active > 1
            # Yield twice, like real DB I/O would, to give a concurrent
            # sibling every chance to interleave.
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            active -= 1
            if overlap:
                raise AssertionError("two exclusive providers ran concurrently")
            return [_summary(base + i) for i in range(4)]

        return RailProvider(
            provider_id,
            provider_id,
            "standard",
            fetch,
            RailType.RECOMMENDED,
            exclusive=True,
        )

    providers = [probe("ex-a", 1000), probe("ex-b", 2000), probe("ex-c", 3000)]
    rails = await _compose_rails(_ctx(FakeCatalog()), providers)

    assert [rail.id for rail in rails] == ["ex-a", "ex-b", "ex-c"]

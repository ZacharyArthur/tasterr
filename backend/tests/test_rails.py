"""Rail providers and the composer: degrade, de-dupe, drop, paginate (tasks 3.2, 3.3)."""

import asyncio
from datetime import date, timedelta
from typing import cast

import pytest
from pydantic import SecretStr

from tasterr.catalog.models import (
    Genre,
    MediaDetail,
    MediaSummary,
    Rail,
    ServiceOption,
    WatchProviders,
)
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.rails.composer import build_extra_rails, build_home
from tasterr.rails.registry import (
    EXTRA_PAGE_SIZE,
    HERO_SIZE,
    RailContext,
    continue_watching_provider,
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
        self.service_results: dict[int, list[MediaSummary]] = {}
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
        if service_ids and service_ids[0] in self.service_results:
            return list(self.service_results[service_ids[0]])
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


async def _all_extra_rails(ctx: RailContext) -> list[Rail]:
    rails: list[Rail] = []
    cursor: int | None = 0
    while cursor is not None:
        page = await build_extra_rails(ctx, cursor)
        rails.extend(page.rails)
        cursor = page.next_cursor
    return rails


class FakePlexCatalog:
    def __init__(self, items: list[MediaSummary] | None = None) -> None:
        self.items = items or []
        self.calls = 0
        self.fail = False

    async def continue_watching(self, user_id: int, account_token: str) -> list[MediaSummary]:
        self.calls += 1
        assert user_id == 1
        assert account_token == "account-token"
        if self.fail:
            raise UpstreamUnavailable("plex down")
        return self.items


def _resume(*ids: int) -> list[MediaSummary]:
    return [_summary(tmdb_id).model_copy(update={"progress_percent": 50}) for tmdb_id in ids]


def _plex_ctx(fake: FakeCatalog, plex: FakePlexCatalog) -> RailContext:
    from tasterr.db.models import User

    user = User(id=1, seerr_user_id=1, display_name="member", auth_type="plex")
    return RailContext(
        cast("CatalogService", fake),
        user=user,
        plex=cast("PlexCatalogService", plex),
        plex_account_token=SecretStr("account-token"),
    )


# ── Providers (3.2) ──────────────────────────────────────────────────────────


def test_home_provider_ids_and_kinds() -> None:
    providers = home_providers()
    assert [p.id for p in providers] == [
        "trending",
        "popular",
        "popular-tv",
        "recently-added",
    ]
    assert providers[1].kind == "standard"
    assert providers[2].title == "Popular TV"
    assert providers[3].title == "Recent Releases"


def test_continue_watching_provider_is_capability_gated_and_nonexclusive() -> None:
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(1, 2, 3, 4))
    provider = continue_watching_provider(_plex_ctx(fake, plex))

    assert provider is not None
    assert provider.id == "continue-watching"
    assert provider.title == "Continue Watching"
    assert provider.exclusive is False
    assert "account-token" not in repr(_plex_ctx(fake, plex))
    assert continue_watching_provider(_ctx(fake)) is None


async def test_continue_watching_token_is_unwrapped_only_during_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = 0
    original = SecretStr.get_secret_value

    def tracked(secret: SecretStr) -> str:
        nonlocal calls
        calls += 1
        return original(secret)

    monkeypatch.setattr(SecretStr, "get_secret_value", tracked)
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(1, 2, 3, 4))
    ctx = _plex_ctx(fake, plex)
    provider = continue_watching_provider(ctx)

    assert provider is not None
    assert calls == 0
    await provider.fetch(ctx)
    assert calls == 1


async def test_continue_watching_is_first_and_owns_cross_rail_duplicates() -> None:
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(1, 20, 21, 22))

    feed = await build_home(_plex_ctx(fake, plex))

    assert feed.rails[0].id == "continue-watching"
    assert [item.id for item in feed.rails[0].items] == [1, 20, 21, 22]
    trending = next(rail for rail in feed.rails if rail.id == "trending")
    assert 1 not in [item.id for item in trending.items]


async def test_disabled_thin_and_failed_continue_watching_do_no_harm() -> None:
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(1, 2, 3))
    thin = await build_home(_plex_ctx(fake, plex))
    assert "continue-watching" not in [rail.id for rail in thin.rails]

    plex.items = _resume(1, 2, 3, 4)
    disabled_ctx = _plex_ctx(fake, plex)
    disabled_ctx.disabled_rail_types = frozenset((RailType.CONTINUE_WATCHING,))
    disabled = await build_home(disabled_ctx)
    assert "continue-watching" not in [rail.id for rail in disabled.rails]
    assert plex.calls == 1

    plex.fail = True
    degraded = await build_home(_plex_ctx(fake, plex))
    assert "continue-watching" not in [rail.id for rail in degraded.rails]
    assert "trending" in [rail.id for rail in degraded.rails]


async def test_continue_watching_fetch_overlaps_but_keeps_response_priority() -> None:
    started: set[str] = set()
    gate = asyncio.Event()
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(20, 21, 22, 23))

    async def wait_for_peer(name: str) -> None:
        started.add(name)
        if len(started) == 2:
            gate.set()
        await gate.wait()

    original_trending = fake.trending
    original_continue = plex.continue_watching

    async def trending() -> list[MediaSummary]:
        await wait_for_peer("trending")
        return await original_trending()

    async def continue_watching(user_id: int, account_token: str) -> list[MediaSummary]:
        await wait_for_peer("plex")
        return await original_continue(user_id, account_token)

    fake.trending = trending  # type: ignore[method-assign]
    plex.continue_watching = continue_watching  # type: ignore[method-assign]

    feed = await build_home(_plex_ctx(fake, plex))

    assert started == {"plex", "trending"}
    assert feed.rails[0].id == "continue-watching"


async def test_popular_providers_query_movies_then_tv() -> None:
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
    await home_providers()[2].fetch(_ctx(fake))
    assert fake.discover_calls[-1]["media"] == "tv"
    assert fake.discover_calls[-1]["min_votes"] == 30


async def test_genre_provider_filters_and_labels_tv() -> None:
    provider = genre_provider(28, "Action", "tv")
    assert provider.id == "genre-tv-28"
    assert provider.title == "Action · TV"
    assert provider.kind == "genre"
    fake = FakeCatalog()
    await provider.fetch(_ctx(fake))
    assert fake.discover_calls[-1]["genres"] == [28]
    assert fake.discover_calls[-1]["min_votes"] == 30
    assert genre_provider(28, "Action", "movie").title == "Action · Movies"


async def test_decade_provider_bounds_release_window() -> None:
    provider = decade_provider(1990)
    assert provider.id == "decade-1990"
    assert provider.title == "1990s"
    fake = FakeCatalog()
    await provider.fetch(_ctx(fake))
    assert fake.discover_calls[-1]["release_gte"] == "1990-01-01"
    assert fake.discover_calls[-1]["release_lte"] == "1999-12-31"


def test_top_rated_provider_ids() -> None:
    providers = top_rated_providers()
    assert [p.id for p in providers] == ["top-rated-movie", "top-rated-tv"]
    assert providers[1].title == "Top Rated TV"


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

    rails = await _all_extra_rails(_ctx(fake))

    service_rails = [rail for rail in rails if rail.id.startswith("service-")]
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

    rails = await _all_extra_rails(_ctx(fake))

    ids = {rail.id for rail in rails}
    assert not any(rail_id.startswith("service-") for rail_id in ids)
    assert {"top-rated-movie", "top-rated-tv"} <= ids


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

    rails = await _all_extra_rails(_ctx(fake))

    ids = {rail.id for rail in rails}
    assert "service-8" not in ids
    assert "service-9" in ids
    assert {"top-rated-movie", "top-rated-tv"} <= ids


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


async def test_cursor_grouping_does_not_underfill_an_overlapping_service_rail() -> None:
    fake = FakeCatalog()
    service_ids = (8, 337, 9, 15)
    fake.selected_service_ids = service_ids
    fake.available_services = [
        ServiceOption(
            provider_id=provider_id,
            name=f"Service {provider_id}",
            logo_path=None,
            display_priority=index,
        )
        for index, provider_id in enumerate(service_ids)
    ]
    fake.service_results[9] = [_summary(tmdb_id) for tmdb_id in range(1, 21)]
    fake.service_results[15] = [
        *[_summary(tmdb_id) for tmdb_id in range(1, 17)],
        *[_summary(tmdb_id) for tmdb_id in range(21, 25)],
    ]

    page = await build_extra_rails(_ctx(fake), 4)
    by_id = {rail.id: rail for rail in page.rails}

    assert len(by_id["service-9"].items) == 20
    assert len(by_id["service-15"].items) == 20


async def test_extra_rails_order_services_decades_then_stable_mixed_genres() -> None:
    fake = FakeCatalog()
    fake.selected_service_ids = (8,)
    fake.available_services = [
        ServiceOption(provider_id=8, name="Netflix", logo_path=None, display_priority=1)
    ]

    rails = await _all_extra_rails(_ctx(fake))
    ids = [rail.id for rail in rails]

    assert ids[:3] == ["top-rated-movie", "top-rated-tv", "service-8"]
    assert ids[3:8] == [f"decade-{decade}" for decade in (2020, 2010, 2000, 1990, 1980)]
    genre_ids = ids[8:]
    assert set(genre_ids) == {
        *(f"genre-movie-{genre_id}" for genre_id in fake.genre_map_result.values()),
        *(f"genre-tv-{genre_id}" for genre_id in fake.genre_map_result.values()),
    }
    assert all(
        rail.title.endswith((" · Movies", " · TV"))
        for rail in rails
        if rail.id.startswith("genre-")
    )

    repeated = await _all_extra_rails(_ctx(FakeCatalog()))
    assert [rail.id for rail in repeated if rail.id.startswith("genre-")] == genre_ids


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
        self.more_like_result: tuple[str, bool, list[MediaSummary]] | None = None
        self.unexpected_items: list[MediaSummary] = []
        self.unexpected_calls = 0
        self.fail = False
        self.fail_unexpected = False

    def _maybe_fail(self) -> None:
        if self.fail:
            raise RuntimeError("engine storage on fire")

    async def my_list(self, user_id: int) -> list[MediaSummary]:
        self._maybe_fail()
        return list(self.my_list_items)

    async def recommended_for_you(self, user_id: int) -> list[MediaSummary]:
        self._maybe_fail()
        return list(self.recommended_items)

    async def more_like(self, user_id: int) -> tuple[str, bool, list[MediaSummary]] | None:
        self._maybe_fail()
        return self.more_like_result

    async def unexpected_picks(self, user_id: int) -> list[MediaSummary]:
        self.unexpected_calls += 1
        if self.fail_unexpected:
            raise RuntimeError("exploration failed")
        self._maybe_fail()
        return list(self.unexpected_items)


def _personal_ctx(fake: FakeCatalog, taste: FakeTaste) -> RailContext:
    from tasterr.db.models import User
    from tasterr.recommend.service import TasteService

    user = User(id=1, seerr_user_id=1, display_name="member", auth_type="plex", is_admin=False)
    return RailContext(cast("CatalogService", fake), user=user, taste=cast("TasteService", taste))


async def test_personalized_home_orders_and_titles_rails() -> None:
    taste = FakeTaste()
    taste.my_list_items = [_summary(500)]  # a one-title list still renders
    taste.recommended_items = [_summary(600 + i) for i in range(6)]
    taste.more_like_result = ("Dune", False, [_summary(700 + i) for i in range(6)])
    taste.unexpected_items = [_summary(900 + i) for i in range(6)]
    fake = FakeCatalog()
    plex = FakePlexCatalog(_resume(800, 801, 802, 803))
    ctx = _personal_ctx(fake, taste)
    ctx.plex = cast("PlexCatalogService", plex)
    ctx.plex_account_token = SecretStr("account-token")

    feed = await build_home(ctx)

    ids = [rail.id for rail in feed.rails]
    assert ids == [
        "continue-watching",
        "my-list",
        "recommended-for-you",
        "trending",
        "more-like",
        "popular",
        "popular-tv",
        "recently-added",
        "unexpected-picks",
    ]
    more_like = feed.rails[4]
    assert more_like.title == "More Like Dune"  # resolved from the source title
    my_list = feed.rails[1]
    assert [item.id for item in my_list.items] == [500]


async def test_plex_watch_source_uses_honest_more_like_title() -> None:
    taste = FakeTaste()
    taste.more_like_result = ("Top Gun", True, [_summary(700 + i) for i in range(6)])

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    rail = next(rail for rail in feed.rails if rail.id == "more-like")
    assert rail.title == "Because You Watched Top Gun"


async def test_unexpected_picks_follows_principal_rails_and_keeps_their_priority() -> None:
    taste = FakeTaste()
    taste.unexpected_items = [_summary(1), _summary(101), *[_summary(900 + i) for i in range(5)]]

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    ids = [rail.id for rail in feed.rails]
    assert ids.index("unexpected-picks") > ids.index("recently-added")
    rail = next(rail for rail in feed.rails if rail.id == "unexpected-picks")
    assert rail.title == "Picks You Wouldn't Usually Watch"
    assert [item.id for item in rail.items] == [900, 901, 902, 903, 904]


async def test_thin_unexpected_picks_are_omitted() -> None:
    taste = FakeTaste()
    taste.unexpected_items = [_summary(900 + i) for i in range(3)]

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    assert "unexpected-picks" not in [rail.id for rail in feed.rails]


async def test_unexpected_picks_disable_and_failure_are_independent(
    caplog: pytest.LogCaptureFixture,
) -> None:
    fake = FakeCatalog()
    taste = FakeTaste()
    taste.unexpected_items = [_summary(900 + i) for i in range(5)]
    disabled = _personal_ctx(fake, taste)
    disabled.disabled_rail_types = frozenset({RailType.UNEXPECTED_PICKS})

    disabled_feed = await build_home(disabled)

    assert "unexpected-picks" not in [rail.id for rail in disabled_feed.rails]
    assert taste.unexpected_calls == 0

    enabled = _personal_ctx(FakeCatalog(), taste)
    enabled.disabled_rail_types = frozenset({RailType.TRENDING, RailType.RECENT})
    source_disabled_feed = await build_home(enabled)

    assert "unexpected-picks" in [rail.id for rail in source_disabled_feed.rails]
    assert taste.unexpected_calls == 1

    taste.fail_unexpected = True
    caplog.set_level("ERROR", logger="tasterr.rails")
    degraded_feed = await build_home(enabled)

    assert "unexpected-picks" not in [rail.id for rail in degraded_feed.rails]
    assert {"popular", "popular-tv"} <= {rail.id for rail in degraded_feed.rails}
    assert taste.unexpected_calls == 2
    assert "rails: unexpected-picks failed" in caplog.text
    assert "exploration failed" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_signalless_user_gets_the_plain_home() -> None:
    taste = FakeTaste()  # no signals → every personalized provider yields []

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))
    plain = await build_home(_ctx(FakeCatalog()))

    assert [rail.id for rail in feed.rails] == [rail.id for rail in plain.rails]
    assert not any(
        rail.id in ("my-list", "recommended-for-you", "more-like", "unexpected-picks")
        for rail in feed.rails
    )


async def test_engine_failure_degrades_to_the_plain_home(
    caplog: pytest.LogCaptureFixture,
) -> None:
    taste = FakeTaste()
    taste.fail = True  # storage/engine errors, not upstream ones
    caplog.set_level("ERROR", logger="tasterr.rails")

    feed = await build_home(_personal_ctx(FakeCatalog(), taste))

    ids = [rail.id for rail in feed.rails]
    assert "trending" in ids
    assert not any(
        rail_id in ("my-list", "recommended-for-you", "more-like", "unexpected-picks")
        for rail_id in ids
    )
    assert "engine storage on fire" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


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


async def test_nonexclusive_work_overlaps_serial_exclusive_providers() -> None:
    from tasterr.rails.composer import _compose_rails  # pyright: ignore[reportPrivateUsage]
    from tasterr.rails.registry import RailProvider

    nonexclusive_started = asyncio.Event()

    async def exclusive(_: RailContext) -> list[MediaSummary]:
        await nonexclusive_started.wait()
        return [_summary(1000 + index) for index in range(4)]

    async def nonexclusive(_: RailContext) -> list[MediaSummary]:
        nonexclusive_started.set()
        return [_summary(2000 + index) for index in range(4)]

    providers = [
        RailProvider(
            "exclusive",
            "exclusive",
            "standard",
            exclusive,
            RailType.RECOMMENDED,
            exclusive=True,
        ),
        RailProvider(
            "nonexclusive",
            "nonexclusive",
            "standard",
            nonexclusive,
            RailType.TRENDING,
        ),
    ]

    rails = await asyncio.wait_for(_compose_rails(_ctx(FakeCatalog()), providers), 0.5)

    assert [rail.id for rail in rails] == ["exclusive", "nonexclusive"]


async def test_exclusive_failure_cancels_started_nonexclusive_work() -> None:
    from tasterr.rails.composer import _compose_rails  # pyright: ignore[reportPrivateUsage]
    from tasterr.rails.registry import RailProvider

    nonexclusive_started = asyncio.Event()
    nonexclusive_cancelled = asyncio.Event()

    async def exclusive(_: RailContext) -> list[MediaSummary]:
        await nonexclusive_started.wait()
        raise RuntimeError("exclusive failed")

    async def nonexclusive(_: RailContext) -> list[MediaSummary]:
        nonexclusive_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            nonexclusive_cancelled.set()
            raise
        raise AssertionError("unreachable")

    providers = [
        RailProvider(
            "exclusive",
            "exclusive",
            "standard",
            exclusive,
            RailType.RECOMMENDED,
            exclusive=True,
        ),
        RailProvider(
            "nonexclusive",
            "nonexclusive",
            "standard",
            nonexclusive,
            RailType.TRENDING,
        ),
    ]

    with pytest.raises(RuntimeError, match="exclusive failed"):
        await _compose_rails(_ctx(FakeCatalog()), providers)

    assert nonexclusive_cancelled.is_set()

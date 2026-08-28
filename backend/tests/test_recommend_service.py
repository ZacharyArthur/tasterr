"""TasteService orchestration over faked catalog/availability + real store."""

import asyncio
from collections.abc import AsyncGenerator
from datetime import date, timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

import tasterr.recommend.service as service_mod
from tasterr.catalog.availability import Availability, AvailabilityService
from tasterr.catalog.facts import TitleFacts
from tasterr.catalog.models import MediaDetail, MediaSummary, MediaType, WatchProviders
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Profile, User, utcnow
from tasterr.recommend import store
from tasterr.recommend.features import FeatureRecord
from tasterr.recommend.service import TasteService
from tasterr.recommend.signals import TitleKey


def _summary(tmdb_id: int, media: MediaType = "movie") -> MediaSummary:
    return MediaSummary(
        id=tmdb_id,
        media_type=media,
        title=f"title-{tmdb_id}",
        overview="",
        poster_path=None,
        backdrop_path=None,
        year=2020,
        vote_average=7.0,
    )


def _detail(tmdb_id: int, recommendations: list[MediaSummary]) -> MediaDetail:
    return MediaDetail(
        **_summary(tmdb_id).model_dump(),
        tagline="",
        external_url=f"https://www.themoviedb.org/movie/{tmdb_id}",
        genres=[],
        runtime=None,
        release_date=None,
        certification=None,
        logo_path=None,
        trailer=None,
        watch=WatchProviders(),
        recommendations=recommendations,
        similar=[],
        seasons=[],
        number_of_seasons=None,
    )


class FakeCatalog:
    def __init__(self) -> None:
        self.region = "US"
        self.selected_service_ids: tuple[int, ...] = ()
        self.facts_calls: list[TitleKey] = []
        self.detail_calls: list[TitleKey] = []
        self.failing_facts: set[TitleKey] = set()
        self.details: dict[TitleKey, MediaDetail] = {}
        self.trending_items: list[MediaSummary] = []
        self.discover_items: list[MediaSummary] = []
        self.discover_items_by_surface: dict[
            tuple[MediaType, str, tuple[int, ...]], list[MediaSummary]
        ] = {}
        self.discover_calls: list[tuple[MediaType, str, tuple[int, ...]]] = []
        self.genres_by_title: dict[TitleKey, list[str]] = {}
        self.providers_by_title: dict[TitleKey, list[int]] = {}

    async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
        self.facts_calls.append((media, tmdb_id))
        if (media, tmdb_id) in self.failing_facts:
            raise UpstreamUnavailable("facts unavailable")
        return TitleFacts(
            tmdb_id=tmdb_id,
            media_type=media,
            title=f"title-{tmdb_id}",
            genres=self.genres_by_title.get((media, tmdb_id), ["Drama"]),
            vote_average=7.0,
            vote_count=1000,
            watch_region=self.region,
            flatrate_provider_ids=self.providers_by_title.get((media, tmdb_id), []),
        )

    async def detail(self, media: MediaType, tmdb_id: int) -> MediaDetail:
        self.detail_calls.append((media, tmdb_id))
        detail = self.details.get((media, tmdb_id))
        if detail is None:
            raise UpstreamUnavailable("detail unavailable")
        return detail

    async def trending(self) -> list[MediaSummary]:
        return self.trending_items

    async def discover(
        self,
        media: MediaType,
        *,
        sort_by: str = "popularity.desc",
        genres: list[int] | None = None,
        **_: object,
    ) -> list[MediaSummary]:
        surface = (media, sort_by, tuple(genres or []))
        self.discover_calls.append(surface)
        return self.discover_items_by_surface.get(surface, self.discover_items)

    async def genre_map(self, media: MediaType) -> dict[str, int]:
        return {"Drama": 18, "Comedy": 35}


class FakeAvailability:
    def __init__(self, available: set[TitleKey] | None = None) -> None:
        self.available = available or set()

    async def batch(self, items: list[TitleKey]) -> dict[str, Availability]:
        return {
            f"{media}:{tmdb_id}": Availability(
                status="available" if (media, tmdb_id) in self.available else "not_requested",
                known=True,
            )
            for media, tmdb_id in items
        }


@pytest.fixture
async def db(tmp_path: Path) -> AsyncGenerator[AsyncSession]:
    engine = create_engine(tmp_path / "tasterr.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        yield session
    await engine.dispose()


def _service(
    db: AsyncSession, catalog: FakeCatalog, availability: FakeAvailability | None = None
) -> TasteService:
    avail = cast("AvailabilityService", availability) if availability is not None else None
    return TasteService(db, cast("CatalogService", catalog), avail)


async def _user(db: AsyncSession) -> int:
    user = User(seerr_user_id=1, display_name="member", auth_type="plex")
    db.add(user)
    await db.flush()
    return user.id


async def test_warm_vectors_skip_facts_fetches(db: AsyncSession) -> None:
    catalog = FakeCatalog()
    record = FeatureRecord(
        vector={"genre:drama": 1.0},
        vote_average=7.0,
        vote_count=100,
        watch_region="US",
    )
    await store.save_features(db, ("movie", 1), record)

    records = await _service(db, catalog).ensure_vectors([("movie", 1)])

    assert catalog.facts_calls == []
    assert records == {("movie", 1): record}


async def test_stale_vector_is_rebuilt_and_persisted(db: AsyncSession) -> None:
    catalog = FakeCatalog()
    old = FeatureRecord(vector={"genre:western": 1.0}, vote_average=5.0, vote_count=10)
    await store.save_features(db, ("movie", 1), old, fetched_at=utcnow() - timedelta(days=40))

    records = await _service(db, catalog).ensure_vectors([("movie", 1)])

    assert catalog.facts_calls == [("movie", 1)]
    assert "genre:drama" in records[("movie", 1)].vector
    fresh = await store.load_features(db, [("movie", 1)], utcnow() - timedelta(minutes=1))
    assert ("movie", 1) in fresh


async def test_wrong_region_vector_is_rebuilt_lazily(db: AsyncSession) -> None:
    catalog = FakeCatalog()
    catalog.region = "GB"
    old = FeatureRecord(vector={"genre:drama": 1.0}, watch_region="US")
    await store.save_features(db, ("movie", 1), old)

    records = await _service(db, catalog).ensure_vectors([("movie", 1)])

    assert catalog.facts_calls == [("movie", 1)]
    assert records[("movie", 1)].watch_region == "GB"


async def test_failing_title_is_skipped_not_fatal(
    db: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    catalog = FakeCatalog()
    catalog.failing_facts = {("movie", 2)}

    records = await _service(db, catalog).ensure_vectors([("movie", 1), ("movie", 2)])

    assert set(records) == {("movie", 1)}
    assert "vector build skipped" in caplog.text
    assert "movie:2" not in caplog.text
    assert all(record.exc_info is None for record in caplog.records)


async def test_fresh_profile_is_served_from_the_materialization(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.save_profile(db, user_id, {"genre:sentinel": 1.0})

    vector = await _service(db, FakeCatalog()).profile_vector(user_id)

    assert vector == {"genre:sentinel": 1.0}  # untouched — no recompute ran


async def test_stale_profile_is_recomputed_on_read(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.save_profile(db, user_id, {"genre:sentinel": 1.0})
    await db.execute(update(Profile).values(computed_at=utcnow() - timedelta(days=2)))

    vector = await _service(db, FakeCatalog()).profile_vector(user_id)

    assert "genre:sentinel" not in vector
    assert vector["genre:drama"] > 0.0  # rebuilt from the request signal's facts


async def test_signalless_user_has_an_empty_profile(db: AsyncSession) -> None:
    user_id = await _user(db)

    assert await _service(db, FakeCatalog()).profile_vector(user_id) == {}
    assert await _service(db, FakeCatalog()).recommended_for_you(user_id) == []


async def test_recommendations_exclude_hidden_and_engaged_titles(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.record_signal(db, user_id, "movie", 99, "not_interested")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(99), _summary(2), _summary(1)])
    catalog.trending_items = [_summary(3), _summary(99)]

    items = await _service(db, catalog).recommended_for_you(user_id)

    ids = {item.id for item in items}
    assert 99 not in ids  # hidden everywhere
    assert 1 not in ids  # already requested — they know about it
    assert {2, 3} <= ids


async def test_candidate_pool_respects_the_cap(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_mod, "CANDIDATE_CAP", 5)
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(i) for i in range(100, 130)])

    items = await _service(db, catalog).recommended_for_you(user_id)

    assert 0 < len(items) <= 5
    # facts built for the capped pool + the signal title, nothing more
    assert len(catalog.facts_calls) <= 6


async def test_unexpected_picks_uses_broad_sources_and_excludes_known_titles(
    db: AsyncSession,
) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.record_signal(db, user_id, "movie", 2, "not_interested")
    await store.save_profile(db, user_id, {"genre:drama": 1.0})
    catalog = FakeCatalog()
    catalog.trending_items = [_summary(1), _summary(2), _summary(10), _summary(11)]
    catalog.discover_items_by_surface = {
        ("movie", "popularity.desc", ()): [_summary(10), _summary(12)],
        ("tv", "popularity.desc", ()): [_summary(13, "tv")],
        ("movie", "primary_release_date.desc", ()): [_summary(14)],
        ("movie", "popularity.desc", (35,)): [_summary(15)],
        ("tv", "popularity.desc", (35,)): [_summary(16, "tv")],
    }
    candidate_keys: list[TitleKey] = [
        ("movie", 10),
        ("movie", 11),
        ("movie", 12),
        ("tv", 13),
        ("movie", 14),
        ("movie", 15),
        ("tv", 16),
    ]
    catalog.genres_by_title = {key: ["Comedy"] for key in candidate_keys}

    items = await _service(db, catalog).unexpected_picks(user_id)

    assert [item.id for item in items] == [10, 11]
    assert set(catalog.facts_calls) == set(catalog.genres_by_title)
    assert ("movie", "popularity.desc", (18,)) not in catalog.discover_calls
    assert ("tv", "popularity.desc", (18,)) not in catalog.discover_calls
    assert ("movie", "popularity.desc", (35,)) in catalog.discover_calls
    assert ("tv", "popularity.desc", (35,)) in catalog.discover_calls


async def test_realistic_profile_supplies_at_least_four_unexpected_picks(
    db: AsyncSession,
) -> None:
    user_id = await _user(db)
    await store.save_profile(
        db,
        user_id,
        {"genre:action": 0.8, "genre:drama": 0.5, "lang:en": 0.3},
    )
    catalog = FakeCatalog()
    catalog.trending_items = [_summary(tmdb_id) for tmdb_id in range(10, 30)]
    catalog.genres_by_title = {("movie", tmdb_id): ["Comedy"] for tmdb_id in range(10, 30)}

    items = await _service(db, catalog).unexpected_picks(user_id)

    assert len(items) >= 4


async def test_unexpected_picks_caps_before_vector_work(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_mod, "CANDIDATE_CAP", 5)
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.save_profile(db, user_id, {"genre:drama": 1.0})
    catalog = FakeCatalog()
    catalog.trending_items = [_summary(tmdb_id) for tmdb_id in range(10, 30)]
    catalog.genres_by_title = {("movie", tmdb_id): ["Comedy"] for tmdb_id in range(10, 15)}

    items = await _service(db, catalog).unexpected_picks(user_id)

    assert len(items) == 2
    assert len(catalog.facts_calls) == 5
    assert catalog.discover_calls == []


async def test_unexpected_picks_without_profile_does_no_catalog_work(db: AsyncSession) -> None:
    user_id = await _user(db)
    catalog = FakeCatalog()

    assert await _service(db, catalog).unexpected_picks(user_id) == []
    assert catalog.facts_calls == []
    assert catalog.discover_calls == []


async def test_unexpected_picks_are_user_specific(db: AsyncSession) -> None:
    alice = await _user(db)
    bob_user = User(seerr_user_id=2, display_name="bob", auth_type="plex")
    db.add(bob_user)
    await db.flush()
    bob = bob_user.id
    await store.record_signal(db, alice, "movie", 1, "request")
    await store.record_signal(db, bob, "movie", 2, "request")
    await store.save_profile(db, alice, {"genre:drama": 1.0})
    await store.save_profile(db, bob, {"genre:comedy": 1.0})
    catalog = FakeCatalog()
    catalog.trending_items = [_summary(tmdb_id) for tmdb_id in range(10, 18)]
    candidate_keys: list[TitleKey] = [("movie", tmdb_id) for tmdb_id in range(10, 18)]
    catalog.genres_by_title = {
        key: ["Drama" if key[1] < 14 else "Comedy"] for key in candidate_keys
    }
    service = _service(db, catalog)

    alice_items = await service.unexpected_picks(alice)
    bob_items = await service.unexpected_picks(bob)

    assert [item.id for item in alice_items] == [14, 15]
    assert [item.id for item in bob_items] == [10, 11]


async def test_household_blend_uses_mean_profile_and_any_member_vetoes(
    db: AsyncSession,
) -> None:
    alice = await _user(db)
    bob_user = User(seerr_user_id=2, display_name="bob", auth_type="plex")
    db.add(bob_user)
    await db.flush()
    bob = bob_user.id
    await store.record_signal(db, alice, "movie", 1, "request")
    await store.record_signal(db, alice, "movie", 21, "not_interested")
    await store.record_signal(db, bob, "movie", 2, "request")
    await store.record_signal(db, bob, "movie", 22, "watchlist")
    await store.save_profile(db, alice, {"genre:drama": 1.0})
    await store.save_profile(db, bob, {"genre:comedy": 1.0})
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(
        1, [_summary(tmdb_id) for tmdb_id in (20, 21, 22, 23, 24)]
    )
    catalog.details[("movie", 2)] = _detail(2, [_summary(25)])
    catalog.genres_by_title = {
        ("movie", 20): ["Drama", "Comedy"],
        ("movie", 23): ["Drama"],
        ("movie", 24): ["Comedy"],
        ("movie", 25): ["Action"],
    }

    items = await _service(db, catalog).household_blend([bob, alice])

    assert items[0].id == 20
    assert {item.id for item in items} == {20, 23, 24, 25}
    assert ("movie", 21) not in catalog.facts_calls
    assert ("movie", 22) not in catalog.facts_calls


async def test_household_blend_rejects_the_whole_empty_profile_audience(
    db: AsyncSession,
) -> None:
    alice = await _user(db)
    bob_user = User(seerr_user_id=2, display_name="bob", auth_type="plex")
    db.add(bob_user)
    await db.flush()
    bob = bob_user.id
    await store.record_signal(db, alice, "movie", 1, "request")
    await store.record_signal(db, bob, "movie", 2, "request")
    await store.save_profile(db, alice, {"genre:drama": 1.0})
    catalog = FakeCatalog()
    catalog.failing_facts.add(("movie", 2))

    with pytest.raises(ValueError, match="profile unavailable"):
        await _service(db, catalog).household_blend([alice, bob])

    assert catalog.detail_calls == []
    assert catalog.discover_calls == []


async def test_household_blend_caps_the_shared_union_before_vector_work(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(service_mod, "CANDIDATE_CAP", 5)
    alice = await _user(db)
    bob_user = User(seerr_user_id=2, display_name="bob", auth_type="plex")
    db.add(bob_user)
    await db.flush()
    bob = bob_user.id
    await store.record_signal(db, alice, "movie", 1, "request")
    await store.record_signal(db, bob, "movie", 2, "request")
    await store.save_profile(db, alice, {"genre:drama": 1.0})
    await store.save_profile(db, bob, {"genre:drama": 1.0})
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(tmdb_id) for tmdb_id in range(100, 130)])
    catalog.details[("movie", 2)] = _detail(2, [_summary(tmdb_id) for tmdb_id in range(200, 230)])

    items = await _service(db, catalog).household_blend([alice, bob])

    assert len(items) == 5
    assert len(catalog.facts_calls) == 5
    assert catalog.detail_calls == [("movie", 1)]


async def test_household_blend_rejects_more_than_six_before_materialization(
    db: AsyncSession,
) -> None:
    catalog = FakeCatalog()

    with pytest.raises(ValueError, match="invalid household audience"):
        await _service(db, catalog).household_blend(list(range(1, 8)))

    assert catalog.facts_calls == []
    assert catalog.detail_calls == []


async def test_concurrent_household_blends_use_independent_sessions(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "concurrent.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with maker() as prepare:
            alice = User(seerr_user_id=1, display_name="alice", auth_type="plex")
            bob = User(seerr_user_id=2, display_name="bob", auth_type="plex")
            prepare.add_all((alice, bob))
            await prepare.flush()
            await store.record_signal(prepare, alice.id, "movie", 1, "request")
            await store.record_signal(prepare, bob.id, "movie", 2, "request")
            await store.save_profile(prepare, alice.id, {"genre:drama": 1.0})
            await store.save_profile(prepare, bob.id, {"genre:drama": 1.0})
            for tmdb_id in range(10, 14):
                await store.save_features(
                    prepare,
                    ("movie", tmdb_id),
                    FeatureRecord(
                        vector={"genre:drama": 1.0},
                        vote_average=7.0,
                        vote_count=1000,
                        watch_region="US",
                    ),
                )
            await prepare.commit()
            user_ids = [alice.id, bob.id]

        async def run() -> list[int]:
            catalog = FakeCatalog()
            catalog.details[("movie", 1)] = _detail(
                1, [_summary(tmdb_id) for tmdb_id in range(10, 14)]
            )
            catalog.details[("movie", 2)] = _detail(2, [])
            async with maker() as session:
                return [
                    item.id for item in await _service(session, catalog).household_blend(user_ids)
                ]

        first, second = await asyncio.gather(run(), run())

        assert first == second == [10, 11, 12, 13]
    finally:
        await engine.dispose()


async def test_in_library_candidate_outranks_its_equal(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(2), _summary(3)])
    availability = FakeAvailability(available={("movie", 3)})

    items = await _service(db, catalog, availability).recommended_for_you(user_id)

    assert next(item.id for item in items) == 3


async def test_selected_service_candidate_gets_the_same_single_boost(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    catalog = FakeCatalog()
    catalog.selected_service_ids = (8,)
    catalog.details[("movie", 1)] = _detail(1, [_summary(2), _summary(3)])
    catalog.providers_by_title[("movie", 3)] = [8]

    service_only = await _service(db, catalog).recommended_for_you(user_id)

    assert next(item.id for item in service_only) == 3

    availability = FakeAvailability(available={("movie", 3)})
    both = await _service(db, catalog, availability).recommended_for_you(user_id)
    assert next(item.id for item in both) == 3


async def test_two_users_with_different_taste_get_different_recommendations(
    db: AsyncSession,
) -> None:
    """The M4 milestone bar: two users, two histories, visibly different rails."""
    alice = await _user(db)
    bob_user = User(seerr_user_id=2, display_name="bob", auth_type="plex")
    db.add(bob_user)
    await db.flush()
    bob = bob_user.id
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(2), _summary(3)])
    catalog.details[("movie", 10)] = _detail(10, [_summary(20), _summary(30)])
    catalog.genres_by_title = {
        ("movie", 1): ["Drama"],
        ("movie", 2): ["Drama"],
        ("movie", 3): ["Drama"],
        ("movie", 10): ["Comedy"],
        ("movie", 20): ["Comedy"],
        ("movie", 30): ["Comedy"],
    }
    await store.record_signal(db, alice, "movie", 1, "request")
    await store.record_signal(db, bob, "movie", 10, "request")

    service = _service(db, catalog)
    alice_rail = {item.id for item in await service.recommended_for_you(alice)}
    bob_rail = {item.id for item in await service.recommended_for_you(bob)}

    assert alice_rail == {2, 3}
    assert bob_rail == {20, 30}


async def test_more_like_ranks_the_sources_related_titles(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    await store.record_signal(db, user_id, "movie", 99, "not_interested")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(2), _summary(99), _summary(1)])

    result = await _service(db, catalog).more_like(user_id)

    assert result is not None
    source_title, is_plex_watch, items = result
    assert source_title == "title-1"
    assert is_plex_watch is False
    assert [item.id for item in items] == [2]  # source + hidden excluded


async def test_more_like_uses_plex_watch_label(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 2, "watched_plex")
    catalog = FakeCatalog()
    catalog.details[("movie", 2)] = _detail(2, [_summary(20)])

    result = await _service(db, catalog).more_like(user_id)

    assert result is not None
    assert (result[0], result[1], [item.id for item in result[2]]) == (
        "title-2",
        True,
        [20],
    )


async def test_more_like_non_watch_source_keeps_label(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 2, "request")
    catalog = FakeCatalog()
    catalog.details[("movie", 2)] = _detail(2, [_summary(20)])

    result = await _service(db, catalog).more_like(user_id)

    assert result is not None
    assert (result[0], result[1]) == ("title-2", False)


async def test_more_like_falls_back_past_hidden_and_unavailable_sources(
    db: AsyncSession,
) -> None:
    user_id = await _user(db)
    old = utcnow() - timedelta(days=3)
    await store.record_signal(db, user_id, "movie", 1, "request", old)
    await store.record_signal(db, user_id, "movie", 2, "watched_plex", old + timedelta(days=1))
    await store.record_signal(db, user_id, "movie", 3, "watchlist", old + timedelta(days=2))
    await store.record_signal(db, user_id, "movie", 3, "not_interested", utcnow())
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(10)])

    result = await _service(db, catalog).more_like(user_id)

    assert result is not None
    assert (result[0], result[1], [item.id for item in result[2]]) == (
        "title-1",
        False,
        [10],
    )


async def test_more_like_daily_rotation_is_stable_and_caps_source_attempts(
    db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    class FixedDate(date):
        current = date(2026, 1, 1)

        @classmethod
        def today(cls) -> date:
            return cls.current

    monkeypatch.setattr(service_mod, "date", FixedDate)
    user_id = await _user(db)
    old = utcnow() - timedelta(days=4)
    for tmdb_id in range(1, 5):
        await store.record_signal(
            db,
            user_id,
            "movie",
            tmdb_id,
            "request",
            old + timedelta(days=tmdb_id),
        )
    catalog = FakeCatalog()
    service = _service(db, catalog)

    assert await service.more_like(user_id) is None
    assert catalog.detail_calls == [("movie", 2), ("movie", 3), ("movie", 4)]

    catalog.detail_calls.clear()
    assert await service.more_like(user_id) is None
    assert catalog.detail_calls == [("movie", 2), ("movie", 3), ("movie", 4)]

    FixedDate.current = date(2026, 1, 2)
    catalog.detail_calls.clear()
    assert await service.more_like(user_id) is None
    assert catalog.detail_calls == [("movie", 3), ("movie", 2), ("movie", 4)]


async def test_my_list_excludes_hidden_titles(db: AsyncSession) -> None:
    """not_interested excludes a title from *every* personalized rail — a
    watchlisted-then-hidden title must not linger in My List."""
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "watchlist")
    await store.record_signal(db, user_id, "movie", 2, "watchlist")
    await store.record_signal(db, user_id, "movie", 1, "not_interested")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [])
    catalog.details[("movie", 2)] = _detail(2, [])

    items = await _service(db, catalog).my_list(user_id)

    assert [item.id for item in items] == [2]


async def test_my_list_returns_active_watchlist_newest_first(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "watchlist", utcnow() - timedelta(days=1))
    await store.record_signal(db, user_id, "movie", 2, "watchlist")
    await store.record_signal(db, user_id, "movie", 3, "watchlist")
    await store.retract_signal(db, user_id, "movie", 2, "watchlist")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [])
    catalog.details[("movie", 3)] = _detail(3, [])

    items = await _service(db, catalog).my_list(user_id)

    assert [item.id for item in items] == [3, 1]

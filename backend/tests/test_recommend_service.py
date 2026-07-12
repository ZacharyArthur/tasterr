"""TasteService orchestration over faked catalog/availability + real store."""

from collections.abc import AsyncGenerator
from datetime import timedelta
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
        self.facts_calls: list[TitleKey] = []
        self.failing_facts: set[TitleKey] = set()
        self.details: dict[TitleKey, MediaDetail] = {}
        self.trending_items: list[MediaSummary] = []
        self.discover_items: list[MediaSummary] = []
        self.genres_by_title: dict[TitleKey, list[str]] = {}

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
        )

    async def detail(self, media: MediaType, tmdb_id: int) -> MediaDetail:
        detail = self.details.get((media, tmdb_id))
        if detail is None:
            raise UpstreamUnavailable("detail unavailable")
        return detail

    async def trending(self) -> list[MediaSummary]:
        return self.trending_items

    async def discover(self, media: MediaType, **_: object) -> list[MediaSummary]:
        return self.discover_items

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
    record = FeatureRecord(vector={"genre:drama": 1.0}, vote_average=7.0, vote_count=100)
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


async def test_failing_title_is_skipped_not_fatal(db: AsyncSession) -> None:
    catalog = FakeCatalog()
    catalog.failing_facts = {("movie", 2)}

    records = await _service(db, catalog).ensure_vectors([("movie", 1), ("movie", 2)])

    assert set(records) == {("movie", 1)}


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


async def test_in_library_candidate_outranks_its_equal(db: AsyncSession) -> None:
    user_id = await _user(db)
    await store.record_signal(db, user_id, "movie", 1, "request")
    catalog = FakeCatalog()
    catalog.details[("movie", 1)] = _detail(1, [_summary(2), _summary(3)])
    availability = FakeAvailability(available={("movie", 3)})

    items = await _service(db, catalog, availability).recommended_for_you(user_id)

    assert next(item.id for item in items) == 3


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
    source_title, items = result
    assert source_title == "title-1"
    assert [item.id for item in items] == [2]  # source + hidden excluded


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

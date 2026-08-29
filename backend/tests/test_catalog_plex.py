import asyncio
from typing import cast

import pytest
from pydantic import SecretStr

import tasterr.catalog.plex as plex_catalog
from tasterr.cache import Cache
from tasterr.catalog.models import MediaDetail, MediaType, WatchProviders
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.plex import (
    PlexCloudAccount,
    PlexGuid,
    PlexMediaClient,
    PlexPmsItem,
    PlexServer,
    PlexServerDiscovery,
)

_MISSING = object()


def _server(index: int) -> PlexServer:
    return PlexServer(
        base_url=f"https://server-{index}.plex.direct:32400",
        machine_identifier=f"server-{index}",
        access_token=SecretStr(f"server-token-{index}"),
    )


def _item(
    tmdb_id: int | None = None,
    *,
    media_type: str = "movie",
    rating_key: int = 1,
    grandparent_rating_key: int | None = None,
    viewed_at: int | None = 100,
    last_viewed_at: int | None = None,
    grandparent_last_viewed_at: int | None = None,
    parent_last_viewed_at: int | None = None,
    view_offset: int | float | None | object = _MISSING,
    duration: int | float | None = None,
    parent_index: int | None = None,
    index: int | None = None,
) -> PlexPmsItem:
    data: dict[str, object] = {
        "accountID": 1,
        "viewedAt": viewed_at,
        "lastViewedAt": last_viewed_at,
        "grandparentLastViewedAt": grandparent_last_viewed_at,
        "parentLastViewedAt": parent_last_viewed_at,
        "type": media_type,
        "ratingKey": rating_key,
        "grandparentRatingKey": grandparent_rating_key,
        "duration": duration,
        "parentIndex": parent_index,
        "index": index,
        "Guid": [] if tmdb_id is None else [PlexGuid(id=f"tmdb://{tmdb_id}")],
    }
    if view_offset is not _MISSING:
        data["viewOffset"] = view_offset
    return PlexPmsItem.model_validate(data)


class FakePlex:
    def __init__(self, servers: int = 1) -> None:
        self.server_list = [_server(index) for index in range(servers)]
        self.histories: dict[str, list[PlexPmsItem] | Exception] = {}
        self.hubs: dict[str, list[PlexPmsItem] | Exception] = {}
        self.metadata_items: dict[tuple[str, str], PlexPmsItem | None | Exception] = {}
        self.history_delays: dict[str, float] = {}
        self.history_active = 0
        self.metadata_calls = 0
        self.metadata_active = 0
        self.metadata_peak = 0
        self.metadata_delay = 0.0
        self.account_calls = 0
        self.discovery_complete = True
        self.resolved_account_ids: dict[str, int] = {}
        self.history_account_ids: list[tuple[str, int]] = []

    async def account(self, _token: str) -> PlexCloudAccount:
        self.account_calls += 1
        return PlexCloudAccount(id=1, username="viewer")

    async def servers(self, _token: str) -> list[PlexServer]:
        return self.server_list

    async def discover_servers(self, _token: str) -> PlexServerDiscovery:
        return PlexServerDiscovery(tuple(self.server_list), self.discovery_complete)

    async def resolve_account_id(self, server: PlexServer, _account: PlexCloudAccount) -> int:
        return self.resolved_account_ids.get(server.machine_identifier, 1)

    async def history(
        self,
        server: PlexServer,
        account_id: int,
        *,
        viewed_after: int,
        viewed_before: int,
    ) -> list[PlexPmsItem]:
        assert viewed_after <= viewed_before
        self.history_account_ids.append((server.machine_identifier, account_id))
        self.history_active += 1
        try:
            await asyncio.sleep(self.history_delays.get(server.machine_identifier, 0))
            result = self.histories.get(server.machine_identifier, [])
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.history_active -= 1

    async def continue_watching(self, server: PlexServer) -> list[PlexPmsItem]:
        result = self.hubs.get(server.machine_identifier, [])
        if isinstance(result, Exception):
            raise result
        return result

    async def metadata(self, server: PlexServer, rating_key: int | str) -> PlexPmsItem | None:
        self.metadata_calls += 1
        self.metadata_active += 1
        self.metadata_peak = max(self.metadata_peak, self.metadata_active)
        try:
            await asyncio.sleep(self.metadata_delay)
            result = self.metadata_items.get(
                (server.machine_identifier, str(rating_key)),
                _item(int(rating_key), rating_key=int(rating_key)),
            )
            if isinstance(result, Exception):
                raise result
            return result
        finally:
            self.metadata_active -= 1


class FakeCatalog:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def detail(self, media_type: MediaType, tmdb_id: int) -> MediaDetail:
        self.calls.append((media_type, tmdb_id))
        return MediaDetail(
            id=tmdb_id,
            media_type=media_type,
            title=f"Title {tmdb_id}",
            overview="",
            poster_path=None,
            backdrop_path=None,
            year=None,
            vote_average=0,
            tagline="",
            external_url="",
            runtime=None,
            release_date=None,
            certification=None,
            logo_path=None,
            trailer=None,
            watch=WatchProviders(),
            number_of_seasons=None,
        )


def _service(fake: FakePlex, catalog: FakeCatalog | None = None) -> PlexCatalogService:
    return PlexCatalogService(
        cast("PlexMediaClient", fake),
        cast("CatalogService", catalog or FakeCatalog()),
        Cache(),
    )


async def test_history_maps_movies_and_episodes_to_canonical_titles() -> None:
    fake = FakePlex()
    fake.histories["server-0"] = [
        _item(10, rating_key=10, viewed_at=300),
        _item(
            media_type="episode",
            rating_key=20,
            grandparent_rating_key=21,
            viewed_at=200,
        ),
        PlexPmsItem(type="movie", ratingKey=30, viewedAt=100, Guid=[PlexGuid(id="tmdb://x")]),
    ]
    fake.metadata_items[("server-0", "21")] = _item(11, rating_key=21)
    fake.metadata_items[("server-0", "30")] = None

    result = await _service(fake).history("account-token", viewed_after=0, viewed_before=400)

    assert [(item.media_type, item.tmdb_id) for item in result.watches] == [
        ("movie", 10),
        ("tv", 11),
    ]
    assert result.complete is True
    assert "account-token" not in repr(result)
    assert "plex.direct" not in repr(result)


async def test_history_retains_completed_servers_when_deadline_expires(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plex_catalog, "HISTORY_DEADLINE_SECONDS", 0.05)
    fake = FakePlex(2)
    fake.histories["server-0"] = [_item(10)]
    fake.histories["server-1"] = [_item(20)]
    fake.history_delays["server-1"] = 1

    result = await _service(fake).history("token", viewed_after=0, viewed_before=200)

    assert [item.tmdb_id for item in result.watches] == [10]
    assert result.complete is False


async def test_history_deadline_cancels_metadata_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plex_catalog, "HISTORY_DEADLINE_SECONDS", 0.02)
    fake = FakePlex()
    fake.histories["server-0"] = [_item(rating_key=10)]
    fake.metadata_delay = 1

    result = await _service(fake).history("token", viewed_after=0, viewed_before=200)

    assert result.complete is False
    assert fake.metadata_calls == 1
    assert fake.metadata_active == 0


async def test_history_parent_cancellation_awaits_server_loads() -> None:
    fake = FakePlex(2)
    fake.history_delays = {"server-0": 60, "server-1": 60}
    task = asyncio.create_task(_service(fake).history("token", viewed_after=0, viewed_before=200))
    while fake.history_active < 2:
        await asyncio.sleep(0)

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert fake.history_active == 0


class _FailingAccountPlex(FakePlex):
    def __init__(self) -> None:
        super().__init__()
        self.discovery_started = asyncio.Event()
        self.discovery_cancelled = False

    async def account(self, _token: str) -> PlexCloudAccount:
        await self.discovery_started.wait()
        raise UpstreamUnavailable("account unavailable")

    async def discover_servers(self, _token: str) -> PlexServerDiscovery:
        self.discovery_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            self.discovery_cancelled = True
            raise
        raise AssertionError("unreachable")


async def test_account_failure_cancels_discovery_for_history_and_continue_watching() -> None:
    history = _FailingAccountPlex()
    with pytest.raises(UpstreamUnavailable):
        await _service(history).history("token", viewed_after=0, viewed_before=200)
    assert history.discovery_cancelled is True

    resume = _FailingAccountPlex()
    assert await _service(resume).continue_watching(1, "token") == []
    assert resume.discovery_cancelled is True


async def test_history_does_not_complete_after_selected_resource_connection_failure() -> None:
    fake = FakePlex()
    fake.discovery_complete = False
    fake.histories["server-0"] = [_item(10)]

    result = await _service(fake).history("token", viewed_after=0, viewed_before=200)

    assert [item.tmdb_id for item in result.watches] == [10]
    assert result.complete is False


async def test_history_bounds_metadata_concurrency_and_total_work() -> None:
    fake = FakePlex(2)
    fake.metadata_delay = 0.001
    fake.histories["server-0"] = [
        _item(rating_key=index, viewed_at=1000 - index) for index in range(1, 301)
    ]
    fake.histories["server-1"] = [
        _item(rating_key=index, viewed_at=700 - index) for index in range(301, 601)
    ]

    result = await _service(fake).history("token", viewed_after=0, viewed_before=1000)

    assert fake.metadata_calls == 500
    assert fake.metadata_peak == 8
    assert len(result.watches) == 500
    assert result.complete is True


async def test_history_merges_duplicates_by_timestamp_then_server_order() -> None:
    fake = FakePlex(2)
    fake.histories["server-0"] = [_item(10, viewed_at=100)]
    fake.histories["server-1"] = [_item(10, viewed_at=200), _item(20, viewed_at=200)]

    result = await _service(fake).history("token", viewed_after=0, viewed_before=300)

    assert [(item.tmdb_id, item.watched_at.timestamp()) for item in result.watches] == [
        (10, 200),
        (20, 200),
    ]


async def test_history_resolves_and_uses_each_servers_own_account_row() -> None:
    fake = FakePlex(2)
    fake.resolved_account_ids = {"server-0": 101, "server-1": 202}

    await _service(fake).history("token", viewed_after=0, viewed_before=300)

    assert sorted(fake.history_account_ids) == [("server-0", 101), ("server-1", 202)]


async def test_continue_watching_maps_progress_episode_context_and_duplicate_order() -> None:
    fake = FakePlex(2)
    fake.hubs["server-0"] = [
        _item(10, last_viewed_at=100, view_offset=5, duration=8),
        _item(
            media_type="episode",
            rating_key=20,
            grandparent_rating_key=21,
            last_viewed_at=200,
            view_offset=50,
            duration=100,
            parent_index=2,
            index=3,
        ),
    ]
    fake.hubs["server-1"] = [
        _item(10, last_viewed_at=100, view_offset=90, duration=100),
    ]
    fake.metadata_items[("server-0", "21")] = _item(11, rating_key=21)

    result = await _service(fake).continue_watching(7, "account-token")

    assert [(item.id, item.progress_percent, item.context) for item in result] == [
        (11, 50, "S2 E3"),
        (10, 62, None),
    ]
    assert (result[0].progress_percent, result[0].context) == (50, "S2 E3")
    assert "account-token" not in repr(result)
    assert "server-token" not in repr(result)


async def test_continue_watching_includes_next_up_by_item_show_and_season_timestamp() -> None:
    fake = FakePlex()
    fake.hubs["server-0"] = [
        _item(
            media_type="episode",
            rating_key=20,
            grandparent_rating_key=21,
            last_viewed_at=500,
            grandparent_last_viewed_at=100,
            parent_last_viewed_at=100,
            parent_index=1,
            index=2,
        ),
        _item(
            media_type="episode",
            rating_key=30,
            grandparent_rating_key=31,
            grandparent_last_viewed_at=400,
            parent_last_viewed_at=600,
            parent_index=2,
            index=3,
        ),
        _item(
            media_type="episode",
            rating_key=40,
            grandparent_rating_key=41,
            parent_last_viewed_at=300,
            parent_index=3,
            index=4,
        ),
    ]
    fake.metadata_items[("server-0", "21")] = _item(11, rating_key=21)
    fake.metadata_items[("server-0", "31")] = _item(12, rating_key=31)
    fake.metadata_items[("server-0", "41")] = _item(13, rating_key=41)

    result = await _service(fake).continue_watching(7, "token")

    assert [(item.id, item.progress_percent, item.context) for item in result] == [
        (11, None, "S1 E2"),
        (12, None, "S2 E3"),
        (13, None, "S3 E4"),
    ]


async def test_continue_watching_preserves_hub_order_without_timestamps() -> None:
    fake = FakePlex(2)
    fake.hubs["server-0"] = [
        _item(
            media_type="episode",
            rating_key=20,
            grandparent_rating_key=21,
            parent_index=1,
            index=2,
        ),
        _item(
            media_type="episode",
            rating_key=30,
            grandparent_rating_key=31,
            parent_index=1,
            index=3,
        ),
    ]
    fake.hubs["server-1"] = [
        _item(
            media_type="episode",
            rating_key=40,
            grandparent_rating_key=41,
            parent_index=1,
            index=4,
        )
    ]
    fake.metadata_items[("server-0", "21")] = _item(11, rating_key=21)
    fake.metadata_items[("server-0", "31")] = _item(12, rating_key=31)
    fake.metadata_items[("server-1", "41")] = _item(13, rating_key=41)

    result = await _service(fake).continue_watching(7, "token")

    assert [(item.id, item.progress_percent) for item in result] == [
        (11, None),
        (13, None),
        (12, None),
    ]


async def test_continue_watching_prefers_progress_on_equal_show_timestamp() -> None:
    fake = FakePlex()
    fake.hubs["server-0"] = [
        _item(
            media_type="episode",
            rating_key=20,
            grandparent_rating_key=21,
            grandparent_last_viewed_at=200,
            parent_index=1,
            index=2,
        ),
        _item(
            media_type="episode",
            rating_key=30,
            grandparent_rating_key=21,
            last_viewed_at=200,
            view_offset=50,
            duration=100,
            parent_index=1,
            index=1,
        ),
    ]
    fake.metadata_items[("server-0", "21")] = _item(11, rating_key=21)

    result = await _service(fake).continue_watching(7, "token")

    assert [(item.id, item.progress_percent, item.context) for item in result] == [
        (11, 50, "S1 E1")
    ]


async def test_continue_watching_skips_invalid_progress_context_and_partial_server() -> None:
    fake = FakePlex(2)
    fake.hubs["server-0"] = [
        _item(1, last_viewed_at=1, view_offset=0, duration=100),
        _item(2, last_viewed_at=2, view_offset=100, duration=100),
        _item(3, last_viewed_at=3, view_offset=1, duration=0),
        _item(7, last_viewed_at=7, view_offset=True, duration=100),
        _item(8, last_viewed_at=8, view_offset=1, duration=True),
        _item(9, last_viewed_at=9, duration=100),
        _item(
            media_type="episode",
            rating_key=4,
            grandparent_rating_key=40,
            last_viewed_at=4,
            view_offset=50,
            duration=100,
            parent_index=0,
            index=1,
        ),
        _item(
            media_type="episode",
            rating_key=10,
            grandparent_rating_key=100,
            last_viewed_at=10,
            view_offset=True,
            duration=100,
            parent_index=1,
            index=1,
        ),
        _item(
            media_type="episode",
            rating_key=11,
            grandparent_rating_key=110,
            last_viewed_at=11,
            view_offset=None,
            duration=100,
            parent_index=1,
            index=2,
        ),
        _item(5, last_viewed_at=5, view_offset=99, duration=100),
        _item(6, last_viewed_at=6, view_offset=1, duration=100),
    ]
    fake.hubs["server-1"] = UpstreamUnavailable("down")

    result = await _service(fake).continue_watching(7, "token")

    assert [(item.id, item.progress_percent) for item in result] == [(6, 1), (5, 99)]


async def test_continue_watching_does_not_hide_programming_errors() -> None:
    fake = FakePlex(2)
    fake.hubs["server-0"] = [_item(rating_key=1, last_viewed_at=1, view_offset=50, duration=100)]
    fake.hubs["server-1"] = AssertionError("programming error")

    with pytest.raises(AssertionError, match="programming error"):
        await _service(fake).continue_watching(7, "token")
    await asyncio.sleep(0)

    assert fake.metadata_calls == 0


async def test_continue_watching_caps_tmdb_resolution_after_merge() -> None:
    fake = FakePlex()
    fake.hubs["server-0"] = [
        _item(
            index,
            rating_key=index,
            last_viewed_at=100 - index,
            view_offset=50,
            duration=100,
        )
        for index in range(1, 26)
    ]
    catalog = FakeCatalog()

    result = await _service(fake, catalog).continue_watching(7, "token")

    assert len(result) == 20
    assert len(catalog.calls) == 20


async def test_continue_watching_caps_metadata_before_guid_expansion() -> None:
    fake = FakePlex()
    fake.hubs["server-0"] = [
        _item(rating_key=1, last_viewed_at=100, view_offset=50, duration=100),
        _item(rating_key=1, last_viewed_at=99, view_offset=40, duration=100),
        *[
            _item(
                rating_key=index,
                last_viewed_at=98 - index,
                view_offset=50,
                duration=100,
            )
            for index in range(2, 26)
        ],
    ]

    result = await _service(fake).continue_watching(7, "token")

    assert len(result) == 20
    assert fake.metadata_calls == 20


async def test_continue_watching_cache_is_positive_negative_and_user_scoped() -> None:
    fake = FakePlex()
    fake.hubs["server-0"] = [_item(1, last_viewed_at=1, view_offset=50, duration=100)]
    service = _service(fake)

    first = await service.continue_watching(7, "first-token")
    fake.hubs["server-0"] = UpstreamUnavailable("down")
    same_user = await service.continue_watching(7, "second-session-token")
    other_user = await service.continue_watching(8, "other-token")
    fake.hubs["server-0"] = [_item(2, last_viewed_at=2, view_offset=50, duration=100)]
    negative_hit = await service.continue_watching(8, "other-token")

    assert first == same_user
    assert other_user == negative_hit == []
    assert fake.account_calls == 2


async def test_continue_watching_timeout_is_negatively_cached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(plex_catalog, "CONTINUE_WATCHING_DEADLINE_SECONDS", 0.02)
    fake = FakePlex()
    calls = 0

    async def hanging_account(_token: str) -> PlexCloudAccount:
        nonlocal calls
        calls += 1
        await asyncio.Event().wait()
        return PlexCloudAccount(id=1, username="viewer")

    fake.account = hanging_account  # type: ignore[method-assign]
    service = _service(fake)

    assert await service.continue_watching(7, "token") == []
    assert await service.continue_watching(7, "token") == []
    assert calls == 1


async def test_continue_watching_expiry_replaces_success_with_negative_then_recovers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 0.0
    monkeypatch.setattr("tasterr.cache.time.monotonic", lambda: now)
    fake = FakePlex()
    fake.hubs["server-0"] = [_item(1, last_viewed_at=1, view_offset=50, duration=100)]
    service = _service(fake)

    assert [item.id for item in await service.continue_watching(7, "token")] == [1]
    now = 301
    fake.hubs["server-0"] = UpstreamUnavailable("down")
    assert await service.continue_watching(7, "token") == []
    now = 602
    fake.hubs["server-0"] = [_item(2, last_viewed_at=2, view_offset=50, duration=100)]
    assert [item.id for item in await service.continue_watching(7, "token")] == [2]
    assert fake.account_calls == 3


async def test_continue_watching_cancellation_propagates_without_caching() -> None:
    fake = FakePlex()
    entered = asyncio.Event()
    release = asyncio.Event()

    async def hanging_account(_token: str) -> PlexCloudAccount:
        entered.set()
        await release.wait()
        return PlexCloudAccount(id=1, username="viewer")

    fake.account = hanging_account  # type: ignore[method-assign]
    service = _service(fake)
    task = asyncio.create_task(service.continue_watching(7, "token"))
    await entered.wait()
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    fake.account = FakePlex.account.__get__(fake)  # type: ignore[method-assign]
    assert await service.continue_watching(7, "token") == []
    assert fake.account_calls == 1

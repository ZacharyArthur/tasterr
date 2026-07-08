import asyncio
from typing import cast

import pytest

from tasterr.cache import Cache, CacheOpts
from tasterr.catalog import availability as avail
from tasterr.catalog.availability import (
    NOT_REQUESTED,
    UNKNOWN,
    Availability,
    AvailabilityService,
    availability_from_code,
    to_availability,
)
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.seerr import MediaType, SeerrClient, SeerrMediaInfo

# ── Pure status mapping ──────────────────────────────────────────────────────


def test_codes_map_to_statuses() -> None:
    assert availability_from_code(2).status == "pending"
    assert availability_from_code(3).status == "processing"
    assert availability_from_code(4).status == "partial"
    assert availability_from_code(5).status == "available"


def test_known_statuses_are_known() -> None:
    assert availability_from_code(5).known is True


def test_seerr_unknown_and_unmapped_codes_fall_back_to_not_requested() -> None:
    # Seerr's own status 1 ("unknown") and any unexpected code are actionable as a
    # request — and stay distinct from UNKNOWN (Seerr unreachable).
    assert availability_from_code(1) == NOT_REQUESTED
    assert availability_from_code(99) == NOT_REQUESTED


def test_absent_media_info_is_not_requested() -> None:
    assert to_availability(None) == NOT_REQUESTED


def test_media_info_maps_to_status() -> None:
    assert to_availability(SeerrMediaInfo(status=5)) == Availability(status="available", known=True)


# ── AvailabilityService: cache, single-flight, degradation ───────────────────


class FakeSeerrClient:
    def __init__(self) -> None:
        self.calls = 0
        self.fail_ids: set[int] = set()
        self.code = 5

    async def media_status(self, media_type: MediaType, tmdb_id: int) -> SeerrMediaInfo | None:
        await asyncio.sleep(0)  # a real yield, so single-flight is genuinely exercised
        self.calls += 1
        if tmdb_id in self.fail_ids:
            raise UpstreamUnavailable("down")
        return SeerrMediaInfo(status=self.code)


def _service(fake: FakeSeerrClient) -> AvailabilityService:
    return AvailabilityService(cast("SeerrClient", fake), Cache())


async def test_fresh_value_skips_the_loader() -> None:
    fake = FakeSeerrClient()
    service = _service(fake)

    assert (await service.status("movie", 1)).status == "available"
    assert (await service.status("movie", 1)).status == "available"
    assert fake.calls == 1  # second call served from cache within TTL


async def test_concurrent_misses_collapse_to_one_fetch() -> None:
    fake = FakeSeerrClient()
    service = _service(fake)

    results = await asyncio.gather(*(service.status("movie", 1) for _ in range(5)))

    assert all(r.status == "available" for r in results)
    assert fake.calls == 1  # single-flight


async def test_cold_error_degrades_to_unknown() -> None:
    fake = FakeSeerrClient()
    fake.fail_ids = {1}
    service = _service(fake)

    assert await service.status("movie", 1) == UNKNOWN


async def test_error_never_serves_a_stale_value(monkeypatch: pytest.MonkeyPatch) -> None:
    # ttl=0 forces a refresh every call; stale=0 means a failed refresh cannot serve
    # the prior value — it must degrade to Unknown (SPEC §10, not TMDB's stale-on-error).
    monkeypatch.setattr(avail, "AVAIL_OPTS", CacheOpts(ttl=0, stale=0))
    fake = FakeSeerrClient()
    service = _service(fake)

    assert (await service.status("movie", 1)).status == "available"  # prime a good value
    fake.fail_ids = {1}
    assert await service.status("movie", 1) == UNKNOWN  # not the stale "available"


async def test_unconfigured_service_is_unknown_without_a_client() -> None:
    service = AvailabilityService(None, Cache())

    assert await service.status("movie", 1) == UNKNOWN


async def test_batch_degrades_per_item() -> None:
    fake = FakeSeerrClient()
    fake.fail_ids = {2}
    service = _service(fake)

    result = await service.batch([("movie", 1), ("tv", 2)])

    assert result["movie:1"].status == "available"
    assert result["tv:2"] == UNKNOWN

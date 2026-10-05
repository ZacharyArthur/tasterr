"""Eligibility, deadline cancellation and per-request lookup reuse."""

import asyncio
from typing import cast

import pytest

import tasterr.catalog.discovery as discovery_mod
from tasterr.cache import Cache
from tasterr.catalog.availability import UNKNOWN, Availability, AvailabilityService
from tasterr.catalog.discovery import DiscoveryFilter
from tasterr.catalog.facts import TitleFacts
from tasterr.catalog.models import MediaType
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.seerr import SeerrClient, SeerrMediaInfo

TitleKey = tuple[MediaType, int]


class Catalog:
    region = "US"

    def __init__(self) -> None:
        self.providers: dict[TitleKey, list[int]] = {}
        self.calls: list[TitleKey] = []
        self.fail = False
        self.fact_region = "US"

    async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
        self.calls.append((media, tmdb_id))
        if self.fail:
            raise UpstreamUnavailable("unavailable")
        return TitleFacts(
            tmdb_id=tmdb_id,
            media_type=media,
            title="Title",
            watch_region=self.fact_region,
            flatrate_provider_ids=self.providers.get((media, tmdb_id), []),
        )


class Library:
    def __init__(self) -> None:
        self.values: dict[TitleKey, Availability] = {}
        self.calls: list[TitleKey] = []
        self.stall = False
        self.cancelled = 0
        self.active = 0
        self.peak = 0

    async def status(self, media: MediaType, tmdb_id: int) -> Availability:
        self.calls.append((media, tmdb_id))
        self.active += 1
        self.peak = max(self.peak, self.active)
        try:
            if self.stall and tmdb_id != 1:
                await asyncio.Event().wait()
            return self.values.get((media, tmdb_id), UNKNOWN)
        except asyncio.CancelledError:
            self.cancelled += 1
            raise
        finally:
            self.active -= 1


def policy(
    catalog: Catalog, library: Library, *, hide: bool = True, excluded: list[int] | None = None
) -> DiscoveryFilter:
    return DiscoveryFilter(
        cast("CatalogService", catalog), cast("AvailabilityService", library), hide, excluded or []
    )


@pytest.mark.parametrize("variant", ["regular_status", "four_k_status"])
@pytest.mark.parametrize("status", ["available", "partial"])
async def test_library_hides_either_variant_and_reuses_boost_reads(
    variant: str, status: str
) -> None:
    catalog, library = Catalog(), Library()
    library.values[("tv", 1)] = Availability.model_validate(
        {"status": "processing", "known": True, variant: status}
    )
    filter_ = policy(catalog, library)
    assert await filter_.eligible([("tv", 1), ("movie", 1)]) == {("movie", 1)}
    assert await filter_.in_library([("tv", 1)]) == {("tv", 1)}
    await filter_.eligible([("tv", 1)])
    assert library.calls == [("tv", 1), ("movie", 1)]
    assert catalog.calls == []


async def test_subscriptions_use_active_region_and_fail_open() -> None:
    catalog, library = Catalog(), Library()
    catalog.providers[("movie", 1)] = [8, 9]
    filter_ = policy(catalog, library, hide=False, excluded=[8])
    assert await filter_.eligible([("movie", 1), ("movie", 2)]) == {("movie", 2)}
    assert library.calls == []
    catalog.fact_region = "GB"
    catalog.providers[("movie", 3)] = [8]
    assert await filter_.eligible([("movie", 3)]) == {("movie", 3)}
    catalog.fail = True
    assert await filter_.eligible([("movie", 4)]) == {("movie", 4)}


async def test_deadline_shared_across_checks_boosts_and_rails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_mod, "VERIFICATION_SECONDS", 0.02)
    catalog, library = Catalog(), Library()
    library.stall = True
    library.values[("movie", 1)] = Availability(
        status="available", known=True, regular_status="available"
    )
    filter_ = policy(catalog, library, excluded=[8])
    keys: list[TitleKey] = [("movie", i) for i in range(1, 151)]
    async with asyncio.timeout(1):
        assert await filter_.eligible(keys) == set(keys) - {("movie", 1)}
        calls = list(library.calls)
        assert await filter_.in_library(keys) == {("movie", 1)}
        assert await filter_.eligible([("movie", 999)]) == {("movie", 999)}
    assert library.calls == calls
    assert library.cancelled > 0
    assert library.active == 0
    assert library.peak <= 8


async def test_pending_processing_and_unknown_are_visible() -> None:
    catalog, library = Catalog(), Library()
    for i, status in enumerate(("pending", "processing", "unknown"), 1):
        library.values[("movie", i)] = Availability.model_validate(
            {"status": status, "regular_status": status, "known": status != "unknown"}
        )
    keys: list[TitleKey] = [("movie", i) for i in range(1, 4)]
    assert await policy(catalog, library).eligible(keys) == set(keys)


async def test_concurrent_outage_checks_reuse_unknown_locally_without_global_failure_cache() -> (
    None
):
    class FailedSeerr:
        calls = 0

        async def media_status(self, media: MediaType, tmdb_id: int) -> SeerrMediaInfo | None:
            self.calls += 1
            await asyncio.sleep(0)
            raise UpstreamUnavailable("unavailable")

    seerr = FailedSeerr()
    availability = AvailabilityService(cast("SeerrClient", seerr), Cache())
    catalog = Catalog()
    filter_ = DiscoveryFilter(cast("CatalogService", catalog), availability, True, [])
    keys: list[TitleKey] = [("movie", 1)]
    eligible_a, eligible_b, boost = await asyncio.gather(
        filter_.eligible(keys), filter_.eligible(keys), filter_.in_library(keys)
    )
    assert eligible_a == eligible_b == set(keys)
    assert boost == set()
    assert seerr.calls == 1
    assert await availability.status("movie", 1) == UNKNOWN
    assert seerr.calls == 2  # Unknown is retained only for this discovery request.


async def test_overlapping_subscription_checks_share_one_failed_lookup() -> None:
    class FailedCatalog(Catalog):
        async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
            self.calls.append((media, tmdb_id))
            await asyncio.sleep(0)
            raise UpstreamUnavailable("unavailable")

    catalog = FailedCatalog()
    filter_ = policy(catalog, Library(), hide=False, excluded=[8])
    keys: list[TitleKey] = [("movie", 1)]
    assert await asyncio.gather(filter_.eligible(keys), filter_.eligible(keys)) == [
        set(keys),
        set(keys),
    ]
    assert catalog.calls == keys


async def test_concurrent_rails_and_boosts_cancel_at_one_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(discovery_mod, "VERIFICATION_SECONDS", 0.02)
    library = Library()
    library.stall = True
    filter_ = policy(Catalog(), library)
    keys: list[TitleKey] = [("movie", i) for i in range(2, 50)]
    async with asyncio.timeout(1):
        results = await asyncio.gather(
            filter_.eligible(keys), filter_.eligible(keys), filter_.in_library(keys)
        )
    assert results == [set(keys), set(keys), set()]
    assert library.active == 0
    assert library.cancelled > 0
    assert library.peak <= 8
    assert len(library.calls) == len(set(library.calls))


async def test_unexpected_verification_failure_drains_siblings_and_releases_locks() -> None:
    started = asyncio.Event()
    cancelled = asyncio.Event()

    class BrokenCatalog(Catalog):
        async def title_facts(self, media: MediaType, tmdb_id: int) -> TitleFacts:
            if tmdb_id == 1:
                await started.wait()
                raise ValueError("invalid internal facts")
            started.set()
            try:
                await asyncio.Event().wait()
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    library = Library()
    filter_ = policy(BrokenCatalog(), library, hide=False, excluded=[8])
    with pytest.raises(ExceptionGroup) as raised:
        async with asyncio.timeout(1):
            await filter_.eligible([("movie", 1), ("movie", 2)])
    assert isinstance(raised.value.exceptions[0], ValueError)
    assert cancelled.is_set()
    # Both the title lock and slot must be available after sibling cancellation.
    async with asyncio.timeout(0.5):
        assert await filter_.in_library([("movie", 2)]) == set()
    assert library.calls == [("movie", 2)]

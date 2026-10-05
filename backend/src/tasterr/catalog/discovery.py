"""Request-scoped, best-effort discovery exclusions with one verification budget."""

import asyncio
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING

from tasterr.catalog.availability import Availability, AvailabilityService
from tasterr.catalog.models import MediaSummary, MediaType
from tasterr.clients.errors import UpstreamError

if TYPE_CHECKING:
    from tasterr.catalog.service import CatalogService

TitleKey = tuple[MediaType, int]
VERIFICATION_SECONDS = 5.0
VERIFICATION_CONCURRENCY = 8
PLAYABLE_STATUSES = frozenset({"available", "partial"})


class DiscoveryFilter:
    def __init__(
        self,
        catalog: "CatalogService",
        availability: AvailabilityService | None,
        hide_library_items: bool,
        excluded_service_ids: list[int],
    ) -> None:
        self._catalog = catalog
        self._availability = availability
        self._hide_library_items = hide_library_items
        self.excluded_service_ids = frozenset(excluded_service_ids)
        self._deadline: float | None = None
        self._semaphore = asyncio.Semaphore(VERIFICATION_CONCURRENCY)
        self._checked: set[TitleKey] = set()
        self._hidden: set[TitleKey] = set()
        self._statuses: dict[TitleKey, Availability] = {}
        self._locks: dict[TitleKey, asyncio.Lock] = {}

    @property
    def deadline(self) -> float | None:
        return self._deadline

    @property
    def expired(self) -> bool:
        return self._deadline is not None and asyncio.get_running_loop().time() >= self._deadline

    async def filter(self, items: list[MediaSummary]) -> list[MediaSummary]:
        await self.eligible([(item.media_type, item.id) for item in items])
        return [item for item in items if (item.media_type, item.id) not in self._hidden]

    async def eligible(self, keys: list[TitleKey]) -> set[TitleKey]:
        await self._run(
            [key for key in dict.fromkeys(keys) if key not in self._checked], self._check
        )
        return set(keys) - self._hidden

    async def in_library(self, keys: list[TitleKey]) -> set[TitleKey]:
        await self._run(
            [key for key in dict.fromkeys(keys) if key not in self._statuses], self._library
        )
        return {key for key in keys if self._playable(key)}

    def _playable(self, key: TitleKey) -> bool:
        status = self._statuses.get(key)
        return (
            status is not None
            and status.known
            and (
                status.regular_status in PLAYABLE_STATUSES
                or status.four_k_status in PLAYABLE_STATUSES
            )
        )

    async def _library(self, key: TitleKey) -> None:
        if self._availability is not None and key not in self._statuses:
            self._statuses[key] = await self._availability.status(*key)
        if self._hide_library_items and self._playable(key):
            self._hidden.add(key)

    async def _check(self, key: TitleKey) -> None:
        if key in self._checked:
            return
        if self._hide_library_items:
            await self._library(key)
        if key not in self._hidden and self.excluded_service_ids:
            try:
                facts = await self._catalog.title_facts(*key)
            except UpstreamError:
                pass
            else:
                if (
                    facts.watch_region == self._catalog.region
                    and self.excluded_service_ids.intersection(facts.flatrate_provider_ids)
                ):
                    self._hidden.add(key)
        self._checked.add(key)

    async def _run(
        self, keys: list[TitleKey], check: Callable[[TitleKey], Awaitable[None]]
    ) -> None:
        loop = asyncio.get_running_loop()
        if self._deadline is None:
            self._deadline = loop.time() + VERIFICATION_SECONDS
        if not keys or self.expired:
            return

        async def one(key: TitleKey) -> None:
            async with self._locks.setdefault(key, asyncio.Lock()), self._semaphore:
                await check(key)

        try:
            async with asyncio.timeout_at(self._deadline):
                async with asyncio.TaskGroup() as tasks:
                    for key in keys:
                        tasks.create_task(one(key))
        except TimeoutError:
            pass

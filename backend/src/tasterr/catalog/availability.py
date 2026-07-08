"""Library availability — Seerr's `mediaInfo` mapped to a typed, secret-free status.

Secret-free by construction: this module imports no application settings (enforced
by tests/test_boundaries.py, which flags any `catalog/` file importing settings).
Seerr errors degrade to Unknown in the service layer — never a stale value (SPEC
§10: Seerr failures flip to Unknown, unlike TMDB's stale-on-error).
"""

import asyncio
from collections.abc import Iterable
from typing import Literal

from pydantic import BaseModel

from tasterr.cache import Cache, CacheOpts
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.clients.seerr import MediaType, SeerrClient, SeerrMediaInfo

AvailabilityStatus = Literal[
    "available", "partial", "processing", "pending", "not_requested", "unknown"
]

# Seerr MediaStatus codes (validated against 3.3.0, docs/SEERR-AUTH-SPIKE.md).
# Code 1 ("unknown" to Seerr) and any unmapped code fall through to not-requested.
_CODE_TO_STATUS: dict[int, AvailabilityStatus] = {
    2: "pending",
    3: "processing",
    4: "partial",
    5: "available",
}

# Short TTL so a fresh request reflects in badges quickly; stale=0 so a failed
# refresh never serves a stale status — the service degrades it to Unknown.
AVAIL_OPTS = CacheOpts(ttl=60, stale=0)
_BATCH_CONCURRENCY = 8


class Availability(BaseModel):
    """A title's library status. `known` is false only when Seerr was unreachable —
    distinguishing "Seerr says not-in-library" from "we couldn't reach Seerr"."""

    status: AvailabilityStatus
    known: bool


UNKNOWN = Availability(status="unknown", known=False)
NOT_REQUESTED = Availability(status="not_requested", known=True)


def availability_from_code(code: int) -> Availability:
    """Map a Seerr MediaStatus code to a *known* Availability. Unmapped codes fall
    back to not-requested (actionable as a request), never to Unknown — Unknown is
    reserved for an unreachable Seerr."""
    return Availability(status=_CODE_TO_STATUS.get(code, "not_requested"), known=True)


def to_availability(media_info: SeerrMediaInfo | None) -> Availability:
    """Map Seerr's `mediaInfo` (or its absence) to a known Availability."""
    if media_info is None:
        return NOT_REQUESTED
    return availability_from_code(media_info.status)


class AvailabilityService:
    """Resolves library availability, degrading every failure to Unknown.

    A `None` client means Seerr is unconfigured — every title is Unknown with no
    call. Successful reads are cached (short TTL, single-flight); failures are
    caught here so they are neither cached nor served stale.
    """

    def __init__(self, client: SeerrClient | None, cache: Cache) -> None:
        self._client = client
        self._cache = cache

    async def status(self, media_type: MediaType, tmdb_id: int) -> Availability:
        client = self._client
        if client is None:
            return UNKNOWN  # Seerr unconfigured — no call

        async def loader() -> Availability:
            return to_availability(await client.media_status(media_type, tmdb_id))

        key = f"seerr:avail:{media_type}:{tmdb_id}"
        try:
            return await self._cache.cached(key, AVAIL_OPTS, loader)
        except UpstreamUnavailable:
            return UNKNOWN  # Seerr unreachable — degrade, don't fail

    async def batch(self, items: Iterable[tuple[MediaType, int]]) -> dict[str, Availability]:
        semaphore = asyncio.Semaphore(_BATCH_CONCURRENCY)

        async def one(media_type: MediaType, tmdb_id: int) -> tuple[str, Availability]:
            async with semaphore:
                return f"{media_type}:{tmdb_id}", await self.status(media_type, tmdb_id)

        pairs = await asyncio.gather(*(one(media_type, tmdb_id) for media_type, tmdb_id in items))
        return dict(pairs)

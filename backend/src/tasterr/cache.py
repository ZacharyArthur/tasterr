"""In-process TTL cache with stale-on-error and single-flight (SPEC §10).

TMDB reads are wrapped here: within a key's TTL the cached value is served with
no upstream call; once stale, a refresh is attempted and — if it fails while a
value is still inside its stale window — the last-good value is served instead of
surfacing the error (transient failures only; a definitive rejection propagates).
Concurrent misses for one key collapse to a single upstream fetch via a per-key
lock.

`cachetools` supplies the bounded value store; freshness, the stale window, and
single-flight are ours — `TTLCache` would auto-evict exactly the expired entries
that stale-on-error must retain. Per-key locks live in a `WeakValueDictionary`,
so a lock is retained exactly while some caller holds/awaits it and collected once
idle — an in-use lock can never be evicted (which would let two loaders race and
an older response overwrite a newer one).
"""

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TypeVar, cast
from weakref import WeakValueDictionary

from cachetools import LRUCache

from tasterr.clients.errors import UpstreamUnavailable

T = TypeVar("T")


@dataclass(frozen=True)
class CacheOpts:
    """Per-endpoint-class freshness bounds, in seconds.

    `ttl` is how long a value is served without a refresh; `stale` is the extra
    window past `ttl` during which a failed refresh may still serve the old value.
    """

    ttl: float
    stale: float


@dataclass
class _Entry:
    value: object
    stored_at: float


class Cache:
    """Async single-flight TTL cache. One instance is shared process-wide."""

    def __init__(self, *, maxsize: int = 1024) -> None:
        self._values: LRUCache[str, _Entry] = LRUCache(maxsize=maxsize)
        # Weak refs: a lock stays alive only while a caller holds/awaits it, then
        # is collected — bounded without a maxsize, and never evicted while in use.
        self._locks: WeakValueDictionary[str, asyncio.Lock] = WeakValueDictionary()

    async def cached(self, key: str, opts: CacheOpts, loader: Callable[[], Awaitable[T]]) -> T:
        entry = self._values.get(key)
        if entry is not None and time.monotonic() - entry.stored_at < opts.ttl:
            return cast("T", entry.value)

        lock = self._locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            self._locks[key] = lock

        async with lock:
            # A caller queued behind an in-flight refresh may now find it fresh.
            entry = self._values.get(key)
            if entry is not None and time.monotonic() - entry.stored_at < opts.ttl:
                return cast("T", entry.value)
            try:
                value = await loader()
            except UpstreamUnavailable:
                entry = self._values.get(key)
                if entry is not None and time.monotonic() - entry.stored_at < opts.ttl + opts.stale:
                    return cast("T", entry.value)
                raise
            self._values[key] = _Entry(value=value, stored_at=time.monotonic())
            return value

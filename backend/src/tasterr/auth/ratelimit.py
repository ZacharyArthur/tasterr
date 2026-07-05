"""In-process per-key token bucket for the login endpoints (SPEC §9, tight).

Single-process by design (SPEC §2) and asyncio-single-threaded, so no locking.
Behind the tunnel all clients may share one peer IP, degrading per-IP to a
global bucket — acceptable at household scale; forwarded-for trust is M6.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class _Bucket:
    tokens: float
    updated: float


class TokenBucket:
    def __init__(
        self,
        capacity: float,
        refill_per_second: float,
        clock: Callable[[], float] = time.monotonic,
        max_keys: int = 1024,
    ) -> None:
        self._capacity = capacity
        self._refill = refill_per_second
        self._clock = clock
        self._max_keys = max_keys
        self._buckets: dict[str, _Bucket] = {}

    def allow(self, key: str) -> bool:
        now = self._clock()
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._prune(now)
            if len(self._buckets) >= self._max_keys:
                # Still full after pruning: a unique-key flood. Fail closed for
                # new keys rather than resetting existing buckets — clearing
                # would hand every exhausted offender a fresh allowance. Real
                # exposure is gated on M6's forwarded-header trust decision.
                return False
            bucket = _Bucket(tokens=self._capacity, updated=now)
            self._buckets[key] = bucket
        else:
            elapsed = now - bucket.updated
            bucket.tokens = min(self._capacity, bucket.tokens + elapsed * self._refill)
            bucket.updated = now
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return True
        return False

    def _prune(self, now: float) -> None:
        # Fully-refilled buckets carry no state worth keeping.
        full_after = self._capacity / self._refill if self._refill > 0 else 0.0
        for key in [k for k, b in self._buckets.items() if now - b.updated >= full_after]:
            del self._buckets[key]

"""Bounded in-process token buckets for login and authenticated mutations.

Single-process by design (SPEC §2) and asyncio-single-threaded, so no locking.
Login keys use the effective client address after Uvicorn's trusted-proxy filter;
authenticated and admin mutations key only by server-derived user id.
"""

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Annotated, cast

from fastapi import Depends, HTTPException, Request

from tasterr.auth.deps import AuthedSession, require_admin, require_session


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
                # exposure is gated by the configured trusted-proxy allowlist.
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


def mutation_rate_limit(
    request: Request,
    authed: Annotated[AuthedSession, Depends(require_session)],
) -> None:
    """Spend shared loose capacity only after session authentication succeeds."""
    bucket = cast("TokenBucket", request.app.state.mutation_bucket)
    if not bucket.allow(str(authed.user.id)):
        raise HTTPException(status_code=429, detail="Too many actions")


def admin_rate_limit(
    request: Request,
    admin: Annotated[AuthedSession, Depends(require_admin)],
) -> None:
    """Spend the separate admin bucket only after admin authority is proven."""
    bucket = cast("TokenBucket", request.app.state.admin_bucket)
    if not bucket.allow(str(admin.user.id)):
        raise HTTPException(status_code=429, detail="Too many admin actions")

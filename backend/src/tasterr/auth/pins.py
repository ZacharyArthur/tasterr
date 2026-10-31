"""Opaque, single-use poll handles for the Plex PIN flow.

plex.tv PIN ids are low-entropy integers; polling by raw id would let an
attacker enumerate ids and steal the session minted when a victim approves
their PIN. Handles are unguessable (256-bit), expire quickly, and die on use.
In-process by design: single process (SPEC §2), nothing worth persisting —
a restart mid-login just means clicking the button again.
"""

import secrets
import time
from collections.abc import Callable
from dataclasses import dataclass

TTL_SECONDS = 600.0
MAX_PENDING = 128


@dataclass
class _Pending[T]:
    payload: T
    created: float
    expires: float
    session_hash: str | None = None


class PinStore[T = int]:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._pending: dict[str, _Pending[T]] = {}

    def create(
        self, payload: T, *, session_hash: str | None = None, ttl: float = TTL_SECONDS
    ) -> str:
        now = self._clock()
        self._prune(now)
        if len(self._pending) >= MAX_PENDING:
            oldest = min(self._pending, key=lambda handle: self._pending[handle].created)
            del self._pending[oldest]
        handle = secrets.token_urlsafe(32)
        self._pending[handle] = _Pending(
            payload=payload, created=now, expires=now + ttl, session_hash=session_hash
        )
        return handle

    def get(self, handle: str, *, session_hash: str | None = None) -> T | None:
        """Look up without consuming — polling repeats until the PIN is claimed."""
        pending = self._pending.get(handle)
        if pending is None or pending.session_hash != session_hash:
            return None
        if self._clock() >= pending.expires:
            del self._pending[handle]
            return None
        return pending.payload

    def pop(self, handle: str, *, session_hash: str | None = None) -> T | None:
        """Atomically take the handle — the single-use step once the PIN is
        claimed. Being synchronous, it cannot interleave with another request's
        pop between awaits, so overlapping polls yield exactly one winner."""
        if self.get(handle, session_hash=session_hash) is None:
            return None
        pending = self._pending.pop(handle)
        if self._clock() >= pending.expires:
            return None
        return pending.payload

    def consume(self, handle: str) -> None:
        self._pending.pop(handle, None)

    def _prune(self, now: float) -> None:
        for handle in [h for h, p in self._pending.items() if now >= p.expires]:
            del self._pending[handle]

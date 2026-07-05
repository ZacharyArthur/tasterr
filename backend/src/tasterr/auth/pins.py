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
class _Pending:
    plex_pin_id: int
    created: float


class PinStore:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._pending: dict[str, _Pending] = {}

    def create(self, plex_pin_id: int) -> str:
        now = self._clock()
        self._prune(now)
        if len(self._pending) >= MAX_PENDING:
            oldest = min(self._pending, key=lambda handle: self._pending[handle].created)
            del self._pending[oldest]
        handle = secrets.token_urlsafe(32)
        self._pending[handle] = _Pending(plex_pin_id=plex_pin_id, created=now)
        return handle

    def get(self, handle: str) -> int | None:
        """Look up without consuming — polling repeats until the PIN is claimed."""
        pending = self._pending.get(handle)
        if pending is None:
            return None
        if self._clock() - pending.created >= TTL_SECONDS:
            del self._pending[handle]
            return None
        return pending.plex_pin_id

    def consume(self, handle: str) -> None:
        self._pending.pop(handle, None)

    def _prune(self, now: float) -> None:
        for handle in [h for h, p in self._pending.items() if now - p.created >= TTL_SECONDS]:
            del self._pending[handle]

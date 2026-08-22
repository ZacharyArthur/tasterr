"""Library availability — Seerr's `mediaInfo` mapped to a typed, secret-free status.

Secret-free by construction: this module imports no application settings (enforced
by tests/test_boundaries.py, which flags any `catalog/` file importing settings).
Seerr errors degrade to Unknown in the service layer — never a stale value (SPEC
§10: Seerr failures flip to Unknown, unlike TMDB's stale-on-error).
"""

import asyncio
from collections.abc import Iterable
from typing import Literal
from urllib.parse import parse_qsl, quote, urlsplit

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
# Partial means some seasons are present and Plex can still play the title.
_PLAYABLE_CODES = frozenset({4, 5})

# Short TTL so a fresh request reflects in badges quickly; stale=0 so a failed
# refresh never serves a stale status — the service degrades it to Unknown.
AVAIL_OPTS = CacheOpts(ttl=60, stale=0)
_BATCH_CONCURRENCY = 8


class PlaybackVariant(BaseModel):
    web_url: str
    app_url: str | None = None
    android_intent_url: str | None = None


class PlaybackLinks(BaseModel):
    regular: PlaybackVariant | None = None
    four_k: PlaybackVariant | None = None


class Availability(BaseModel):
    """A title's library status. `known` is false only when Seerr was unreachable —
    distinguishing "Seerr says not-in-library" from "we couldn't reach Seerr"."""

    status: AvailabilityStatus
    known: bool
    playback: PlaybackLinks | None = None


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
    codes = [code for code in (media_info.status, media_info.status_4k) if code in _CODE_TO_STATUS]
    availability = availability_from_code(max(codes, default=0))
    regular = (
        _playback_variant(media_info.web_url, media_info.app_url)
        if media_info.status in _PLAYABLE_CODES
        else None
    )
    four_k = (
        _playback_variant(media_info.web_url_4k, media_info.app_url_4k)
        if media_info.status_4k in _PLAYABLE_CODES
        else None
    )
    playback = PlaybackLinks(regular=regular, four_k=four_k) if regular or four_k else None
    return availability.model_copy(update={"playback": playback})


def _playback_variant(web_url: str | None, app_url: str | None) -> PlaybackVariant | None:
    safe_web = _safe_web_url(web_url)
    if safe_web is None:
        return None
    safe_app = _safe_app_url(app_url)
    android = _android_intent_url(safe_app, safe_web) if safe_app is not None else None
    return PlaybackVariant(web_url=safe_web, app_url=safe_app, android_intent_url=android)


def _safe_web_url(value: str | None) -> str | None:
    if value is None or _has_unsafe_chars(value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "https"
        or parsed.hostname is None
        or parsed.hostname.lower() != "app.plex.tv"
        or parsed.username is not None
        or parsed.password is not None
        or port not in (None, 443)
        or _has_plex_token_parameter(parsed.query)
        or _has_plex_token_parameter(parsed.fragment.split("?", 1)[-1])
    ):
        return None
    return value


def _safe_app_url(value: str | None) -> str | None:
    if value is None or "#" in value or _has_unsafe_chars(value):
        return None
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        return None
    if (
        parsed.scheme.lower() != "plex"
        or parsed.hostname is None
        or parsed.hostname.lower() != "preplay"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.path not in ("", "/")
        or not parsed.query
        or parsed.fragment
        or _has_plex_token_parameter(parsed.query)
    ):
        return None
    return value


def _android_intent_url(app_url: str, web_url: str) -> str:
    target = app_url.split("://", 1)[1]
    fallback = quote(web_url, safe="")
    return (
        f"intent://{target}#Intent;scheme=plex;package=com.plexapp.android;"
        f"S.browser_fallback_url={fallback};end"
    )


def _has_unsafe_chars(value: str) -> bool:
    return value.strip() != value or any(ord(char) < 32 or ord(char) == 127 for char in value)


def _has_plex_token_parameter(value: str) -> bool:
    return any(
        name.casefold() == "x-plex-token" for name, _ in parse_qsl(value, keep_blank_values=True)
    )


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

"""Seerr endpoints (SPEC §4.1/§4.3/§6) — the only module that talks to Seerr.

Auth doctrine: the global SEERR_API_KEY authenticates **reads** (availability,
request history — server-initiated, explicitly scoped by parameter), while
user-attributed **mutations** (creating requests) ride only the member's own
session cookie — the two are never crossed (privilege confusion: the key on a
mutation would forge attribution and bypass quota; a cookie on a read would
break when the member's Seerr session lapses). Contract validated against
Seerr 3.3.0 (docs/SEERR-AUTH-SPIKE.md).
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

SESSION_COOKIE = "connect.sid"
MediaType = Literal["movie", "tv"]
# Short timeout, no retry (SPEC §10): a Seerr blip degrades to Unknown, never a
# retry storm across a rail's worth of availability reads.
SEERR_TIMEOUT_SECONDS = 5.0
# A freshly created request is pending until Seerr's response says otherwise.
MEDIA_STATUS_PENDING = 2


class SeerrUser(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    display_name: str | None = Field(default=None, alias="displayName")
    plex_username: str | None = Field(default=None, alias="plexUsername")
    email: str | None = None
    avatar: str | None = None
    permissions: int = 0

    @property
    def resolved_display_name(self) -> str:
        return self.display_name or self.plex_username or self.email or f"user-{self.id}"


@dataclass
class SeerrLogin:
    user: SeerrUser
    cookie: str  # "connect.sid=<value>" — stored server-side only, never sent to a browser


class SeerrAuthClient:
    def __init__(self, http: httpx.AsyncClient, base_url: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")

    async def login_plex(self, auth_token: str) -> SeerrLogin:
        return await self._login("/api/v1/auth/plex", {"authToken": auth_token})

    async def login_local(self, email: str, password: str) -> SeerrLogin:
        return await self._login("/api/v1/auth/local", {"email": email, "password": password})

    async def _login(self, path: str, payload: dict[str, str]) -> SeerrLogin:
        try:
            response = await self._http.post(f"{self._base}{path}", json=payload)
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 500:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        if response.status_code >= 400:
            raise UpstreamRejected(response.status_code)
        cookie = response.cookies.get(SESSION_COOKIE)
        if cookie is None:
            raise UpstreamUnavailable("seerr login set no session cookie")
        try:
            user = SeerrUser.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error
        return SeerrLogin(user=user, cookie=f"{SESSION_COOKIE}={cookie}")


# ── Availability + request wire models (raw Seerr shapes) ─────────────────────


class SeerrSeasonStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    season_number: int = Field(default=0, alias="seasonNumber")
    status: int = 0


class SeerrMediaInfo(BaseModel):
    """Seerr's `mediaInfo` block. `status` is its MediaStatus (1 unknown, 2 pending,
    3 processing, 4 partially available, 5 available); `seasons` carries per-season
    status for TV. catalog/availability.py maps this to the domain model."""

    model_config = ConfigDict(extra="ignore")

    status: int = 0
    seasons: list[SeerrSeasonStatus] = []


class _SeerrTitle(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_info: SeerrMediaInfo | None = Field(default=None, alias="mediaInfo")


class _SeerrStatus(BaseModel):
    model_config = ConfigDict(extra="ignore")

    version: str


class _SeerrRequestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    media: SeerrMediaInfo | None = None


class _SeerrHistoryMedia(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    tmdb_id: int | None = Field(default=None, alias="tmdbId")
    media_type: str = Field(default="", alias="mediaType")


class _SeerrHistoryRow(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    created_at: str = Field(default="", alias="createdAt")
    media: _SeerrHistoryMedia | None = None


class _SeerrHistoryPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[_SeerrHistoryRow] = []


@dataclass
class SeerrHistoricalRequest:
    """One of the member's past requests — the cold-start seed's input."""

    media_type: MediaType
    tmdb_id: int
    created_at: datetime  # naive UTC, matching the DB convention


HISTORY_PAGE_SIZE = 50
HISTORY_MAX_ROWS = 200  # the seed only needs recent taste, not an archive


class SeerrClient:
    """Availability reads (global API key) and request-as-user (per-user cookie).

    Constructed per request from settings; shares the process-wide httpx client.
    Short timeout, no retry — failures surface for the caller to degrade.
    """

    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._api_key = api_key

    async def probe(self) -> None:
        url = f"{self._base}/api/v1/status"
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._http.get(url, headers=headers, timeout=SEERR_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 500:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        if response.status_code >= 400:
            raise UpstreamRejected(response.status_code)
        try:
            _SeerrStatus.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error

    async def media_status(self, media_type: MediaType, tmdb_id: int) -> SeerrMediaInfo | None:
        """The title's `mediaInfo`, or None when Seerr holds no record (a `404` or
        an absent block — both mean not-requested). Raises UpstreamUnavailable on
        any other failure so the availability service can degrade to Unknown.

        Authenticated by the global API key only — no user cookie rides along."""
        url = f"{self._base}/api/v1/{media_type}/{tmdb_id}"
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._http.get(url, headers=headers, timeout=SEERR_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code == 404:
            return None  # known: Seerr has no media record for this title
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        try:
            return _SeerrTitle.model_validate(response.json()).media_info
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error

    async def list_requests(self, requested_by: int) -> list[SeerrHistoricalRequest]:
        """The member's request history, newest pages first, capped at
        HISTORY_MAX_ROWS. A read scoped by the explicit `requestedBy` filter,
        authenticated by the global key (module doctrine) — never a cookie.
        Rows missing a TMDB id, a movie/tv type, or a parseable date are
        skipped. The walk is bounded by *raw* pages requested, not parsed
        rows, so a misbehaving upstream serving full pages of malformed rows
        can never extend it past HISTORY_MAX_ROWS/HISTORY_PAGE_SIZE requests.
        Raises UpstreamUnavailable/UpstreamRejected on failure."""
        out: list[SeerrHistoricalRequest] = []
        for skip in range(0, HISTORY_MAX_ROWS, HISTORY_PAGE_SIZE):
            page = await self._request_page(requested_by, skip)
            for row in page.results:
                parsed = _historical_request(row)
                if parsed is not None and len(out) < HISTORY_MAX_ROWS:
                    out.append(parsed)
            if len(page.results) < HISTORY_PAGE_SIZE:
                break
        return out

    async def _request_page(self, requested_by: int, skip: int) -> _SeerrHistoryPage:
        url = f"{self._base}/api/v1/request"
        params: dict[str, str | int] = {
            "take": HISTORY_PAGE_SIZE,
            "skip": skip,
            "requestedBy": requested_by,
            "sort": "added",
        }
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._http.get(
                url, params=params, headers=headers, timeout=SEERR_TIMEOUT_SECONDS
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 500:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        if response.status_code >= 400:
            raise UpstreamRejected(response.status_code)
        try:
            return _SeerrHistoryPage.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error

    async def create_request(self, cookie: str, media_type: MediaType, tmdb_id: int) -> int:
        """Create a request attributed to the member (their cookie only — never the
        global key). A TV title requests the whole series at the default quality.
        Returns the resulting media-status code. Raises UpstreamRejected(403) for an
        invalid session or denied request (the caller runs the re-auth ladder),
        UpstreamRejected for other 4xx, UpstreamUnavailable for transport/5xx."""
        url = f"{self._base}/api/v1/request"
        payload: dict[str, object] = {"mediaType": media_type, "mediaId": tmdb_id}
        if media_type == "tv":
            payload["seasons"] = "all"
        headers = {"Cookie": cookie, "Accept": "application/json"}
        try:
            response = await self._http.post(
                url, json=payload, headers=headers, timeout=SEERR_TIMEOUT_SECONDS
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 500:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        if response.status_code >= 400:
            raise UpstreamRejected(response.status_code)
        try:
            result = _SeerrRequestResult.model_validate(response.json())
        except ValueError:
            return MEDIA_STATUS_PENDING  # accepted; unparseable body → assume pending
        return result.media.status if result.media is not None else MEDIA_STATUS_PENDING


def _historical_request(row: _SeerrHistoryRow) -> SeerrHistoricalRequest | None:
    if row.media is None or row.media.tmdb_id is None:
        return None
    if row.media.media_type not in ("movie", "tv"):
        return None
    media_type: MediaType = "tv" if row.media.media_type == "tv" else "movie"
    try:
        parsed = datetime.fromisoformat(row.created_at.replace("Z", "+00:00"))
    except ValueError:
        return None
    created_at = parsed.astimezone(UTC).replace(tzinfo=None) if parsed.tzinfo else parsed
    return SeerrHistoricalRequest(
        media_type=media_type, tmdb_id=row.media.tmdb_id, created_at=created_at
    )

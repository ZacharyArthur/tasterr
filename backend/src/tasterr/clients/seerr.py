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
from enum import IntFlag
from typing import Literal

import httpx
from pydantic import AliasChoices, BaseModel, ConfigDict, Field

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

SESSION_COOKIE = "connect.sid"
MediaType = Literal["movie", "tv"]
# Short timeout, no retry (SPEC §10): a Seerr blip degrades to Unknown, never a
# retry storm across a rail's worth of availability reads.
SEERR_TIMEOUT_SECONDS = 5.0
# A freshly created request is pending until Seerr's response says otherwise.
MEDIA_STATUS_PENDING = 2
# Seerr's service-discovery endpoints are per-*arr-app, not per-media-type —
# movies route to Radarr, TV to Sonarr.
_SERVICE_BY_MEDIA_TYPE: dict[MediaType, str] = {"movie": "radarr", "tv": "sonarr"}


class SeerrPermission(IntFlag):
    ADMIN = 2
    MANAGE_REQUESTS = 16
    REQUEST = 32
    REQUEST_4K = 1024
    REQUEST_4K_MOVIE = 2048
    REQUEST_4K_TV = 4096
    REQUEST_ADVANCED = 8192
    REQUEST_MOVIE = 262144
    REQUEST_TV = 524288


class SeerrUser(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    display_name: str | None = Field(default=None, alias="displayName")
    plex_username: str | None = Field(default=None, alias="plexUsername")
    email: str | None = None
    avatar: str | None = None
    permissions: int = Field(default=0, ge=0)

    def can_request(self, media_type: MediaType, *, is_4k: bool = False) -> bool:
        # Seerr 3.3.0: Manage Requests grants advanced controls, not requesting.
        if is_4k:
            mask = SeerrPermission.REQUEST_4K | (
                SeerrPermission.REQUEST_4K_MOVIE
                if media_type == "movie"
                else SeerrPermission.REQUEST_4K_TV
            )
        else:
            mask = SeerrPermission.REQUEST | (
                SeerrPermission.REQUEST_MOVIE
                if media_type == "movie"
                else SeerrPermission.REQUEST_TV
            )
        return bool(self.permissions & (SeerrPermission.ADMIN | mask))

    @property
    def can_override(self) -> bool:
        return bool(
            self.permissions
            & (
                SeerrPermission.ADMIN
                | SeerrPermission.MANAGE_REQUESTS
                | SeerrPermission.REQUEST_ADVANCED
            )
        )

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

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    status: int = 0
    status_4k: int = Field(default=0, alias="status4k")
    seasons: list[SeerrSeasonStatus] = []
    web_url: str | None = Field(default=None, validation_alias=AliasChoices("plexUrl", "mediaUrl"))
    app_url: str | None = Field(default=None, alias="iOSPlexUrl")
    web_url_4k: str | None = Field(
        default=None, validation_alias=AliasChoices("plexUrl4k", "mediaUrl4k")
    )
    app_url_4k: str | None = Field(default=None, alias="iOSPlexUrl4k")


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


class SeerrQualityProfile(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str


class SeerrRootFolder(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    path: str


class SeerrServer(BaseModel):
    """One configured Radarr/Sonarr server entry (`service/{radarr|sonarr}`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    name: str
    is_default: bool = Field(default=False, alias="isDefault")
    is_4k: bool = Field(default=False, alias="is4k")
    active_profile_id: int = Field(default=0, alias="activeProfileId")
    active_directory: str = Field(default="", alias="activeDirectory")


class SeerrServerDetail(BaseModel):
    """A server's available destinations (`service/{radarr|sonarr}/{id}`)."""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    server: SeerrServer
    profiles: list[SeerrQualityProfile] = []
    root_folders: list[SeerrRootFolder] = Field(default=[], alias="rootFolders")


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

    async def user(self, user_id: int) -> SeerrUser:
        """Fresh capabilities from a server-derived user id, using the read key."""
        try:
            response = await self._http.get(
                f"{self._base}/api/v1/user/{user_id}",
                headers={"X-Api-Key": self._api_key, "Accept": "application/json"},
                timeout=SEERR_TIMEOUT_SECONDS,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 400:
            raise UpstreamUnavailable("seerr user read failed")
        try:
            user = SeerrUser.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error
        if user.id != user_id:
            raise UpstreamUnavailable("unexpected seerr user identity")
        return user

    async def list_servers(self, media_type: MediaType) -> list[SeerrServer]:
        """Every configured destination for this media type (`radarr` for movies,
        `sonarr` for TV) — household configuration, read with the global key.
        Raises UpstreamUnavailable on failure so the caller can degrade to an
        empty destinations list rather than fail the request flow."""
        service = _SERVICE_BY_MEDIA_TYPE[media_type]
        url = f"{self._base}/api/v1/service/{service}"
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._http.get(url, headers=headers, timeout=SEERR_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        try:
            return [SeerrServer.model_validate(item) for item in response.json()]
        except ValueError as error:
            raise UpstreamUnavailable("unexpected seerr response shape") from error

    async def server_destinations(self, media_type: MediaType, server_id: int) -> SeerrServerDetail:
        """A server's available quality profiles and root folders. Raises
        UpstreamUnavailable (including for an unknown server id, which Seerr
        reports via a non-2xx) so the caller degrades the same way as any other
        destinations failure."""
        service = _SERVICE_BY_MEDIA_TYPE[media_type]
        url = f"{self._base}/api/v1/service/{service}/{server_id}"
        headers = {"X-Api-Key": self._api_key, "Accept": "application/json"}
        try:
            response = await self._http.get(url, headers=headers, timeout=SEERR_TIMEOUT_SECONDS)
        except httpx.HTTPError:
            raise UpstreamUnavailable("seerr request failed") from None
        if response.status_code >= 400:
            raise UpstreamUnavailable(f"seerr returned {response.status_code}")
        try:
            return SeerrServerDetail.model_validate(response.json())
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

    async def create_request(
        self,
        cookie: str,
        media_type: MediaType,
        tmdb_id: int,
        *,
        is_4k: bool = False,
        server_id: int | None = None,
        profile_id: int | None = None,
        root_folder: str | None = None,
        seasons: list[int] | None = None,
    ) -> int:
        """Create a request attributed to the member (their cookie only — never the
        global key). A TV title requests the whole series in the selected variant,
        or only `seasons` when given (ignored for a movie).
        When given, `server_id`/`profile_id`/`root_folder` select a non-default
        destination (the caller validates these against the title's real
        destinations first — this method forwards them as-is). Returns the
        resulting media-status code. Raises UpstreamRejected(403) for an
        invalid session or denied request (the caller runs the re-auth ladder),
        UpstreamRejected for other 4xx, UpstreamUnavailable for transport/5xx."""
        url = f"{self._base}/api/v1/request"
        payload: dict[str, object] = {"mediaType": media_type, "mediaId": tmdb_id}
        if is_4k:
            payload["is4k"] = True
        if media_type == "tv":
            payload["seasons"] = seasons if seasons is not None else "all"
        if server_id is not None:
            payload["serverId"] = server_id
        if profile_id is not None:
            payload["profileId"] = profile_id
        if root_folder is not None:
            payload["rootFolder"] = root_folder
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
        if result.media is None:
            return MEDIA_STATUS_PENDING
        code = result.media.status_4k if is_4k else result.media.status
        return code if code >= 2 else MEDIA_STATUS_PENDING


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

"""Seerr endpoints (SPEC §4.1/§4.3/§6) — the only module that talks to Seerr.

Login and request calls authenticate by credential/token/cookie only; the global
SEERR_API_KEY is attached to *availability reads only* (not user-attributed) and
never to a user flow (privilege confusion). Availability reads use the global key;
requests use the per-user cookie — the two are never crossed. Contract validated
against Seerr 3.3.0 (docs/SEERR-AUTH-SPIKE.md).
"""

from dataclasses import dataclass
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


class _SeerrRequestResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    media: SeerrMediaInfo | None = None


class SeerrClient:
    """Availability reads (global API key) and request-as-user (per-user cookie).

    Constructed per request from settings; shares the process-wide httpx client.
    Short timeout, no retry — failures surface for the caller to degrade.
    """

    def __init__(self, http: httpx.AsyncClient, base_url: str, api_key: str) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._api_key = api_key

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

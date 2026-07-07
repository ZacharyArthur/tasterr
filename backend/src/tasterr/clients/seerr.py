"""Seerr auth endpoints (SPEC §4.1) — the only module that talks to Seerr.

Login calls authenticate by credential/token only; the global SEERR_API_KEY is
deliberately never attached to user flows (privilege confusion). Contract
validated against Seerr 3.3.0 (docs/SEERR-AUTH-SPIKE.md).
"""

from dataclasses import dataclass

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

SESSION_COOKIE = "connect.sid"


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

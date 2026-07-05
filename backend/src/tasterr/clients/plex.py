"""plex.tv PIN flow (SPEC §4.1) — the only module that talks to plex.tv."""

from urllib.parse import urlencode

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

PINS_URL = "https://plex.tv/api/v2/pins"
AUTH_URL = "https://app.plex.tv/auth"
PRODUCT = "Tasterr"


class PlexPin(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    code: str


class _PinStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    auth_token: str | None = Field(default=None, alias="authToken")


class PlexAuthClient:
    def __init__(self, http: httpx.AsyncClient, client_identifier: str) -> None:
        self._http = http
        self._client_identifier = client_identifier

    def _headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "X-Plex-Product": PRODUCT,
            "X-Plex-Client-Identifier": self._client_identifier,
        }

    async def create_pin(self) -> PlexPin:
        try:
            response = await self._http.post(
                PINS_URL, params={"strong": "true"}, headers=self._headers()
            )
        except httpx.HTTPError as error:
            raise UpstreamUnavailable(str(error)) from error
        _raise_for_status(response)
        try:
            return PlexPin.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected plex.tv response shape") from error

    async def poll_pin(self, pin_id: int) -> str | None:
        """The Plex auth token once the user has approved the PIN, else None.
        plex.tv answers 404 for expired or unknown PINs."""
        try:
            response = await self._http.get(f"{PINS_URL}/{pin_id}", headers=self._headers())
        except httpx.HTTPError as error:
            raise UpstreamUnavailable(str(error)) from error
        _raise_for_status(response)
        try:
            return _PinStatus.model_validate(response.json()).auth_token
        except ValueError as error:
            raise UpstreamUnavailable("unexpected plex.tv response shape") from error

    def auth_url(self, code: str) -> str:
        fragment = urlencode(
            {
                "clientID": self._client_identifier,
                "code": code,
                "context[device][product]": PRODUCT,
            }
        )
        return f"{AUTH_URL}#?{fragment}"


def _raise_for_status(response: httpx.Response) -> None:
    if response.status_code >= 500:
        raise UpstreamUnavailable(f"plex.tv returned {response.status_code}")
    if response.status_code >= 400:
        raise UpstreamRejected(response.status_code)

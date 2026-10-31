"""Bounded Trakt reads and OAuth, using fixed hosts and header-only API auth."""

import asyncio
from datetime import datetime
from importlib.metadata import version
from typing import Literal, NamedTuple

import httpx
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

AUTH_BASE = "https://auth.trakt.tv"
API_BASE = "https://api.trakt.tv"
REDIRECT_URI = "http://localhost"
TIMEOUT_SECONDS = 10.0
MAX_RESPONSE_BYTES = 8 * 1024 * 1024
HistoryType = Literal["movies", "episodes"]
DeviceStatus = Literal["pending", "slow_down", "expired", "denied"]


class _Model(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class DeviceCode(_Model):
    device_code: str = Field(min_length=1, repr=False)
    user_code: str = Field(min_length=1, max_length=256)
    interval: int = Field(gt=0)
    expires_in: int = Field(gt=0)


class TokenResponse(_Model):
    access_token: str = Field(min_length=1, repr=False)
    refresh_token: str = Field(min_length=1, repr=False)
    created_at: int = Field(ge=0)
    expires_in: int = Field(gt=0)


class TraktIds(_Model):
    tmdb: int | None = None


class TraktTitle(_Model):
    ids: TraktIds = Field(default_factory=TraktIds)


class HistoryPlay(_Model):
    watched_at: datetime | None = None
    movie: TraktTitle | None = None
    show: TraktTitle | None = None


class _UserIds(_Model):
    uuid: str = Field(min_length=1, max_length=4096)


class TraktUser(_Model):
    username: str = Field(min_length=1, max_length=4096)
    ids: _UserIds


class UserSettings(_Model):
    user: TraktUser


class _Activity(_Model):
    watched_at: datetime | None = None


class LastActivities(_Model):
    movies: _Activity = Field(default_factory=_Activity)
    episodes: _Activity = Field(default_factory=_Activity)


class HistoryPage(NamedTuple):
    items: list[HistoryPlay]
    page_count: int | None = None
    page_limit: int | None = None


_PLAYS = TypeAdapter(list[HistoryPlay])


class TraktClient:
    def __init__(
        self, http: httpx.AsyncClient, client_id: str, client_secret: str | None = None
    ) -> None:
        self._http = http
        self._client_id = client_id
        self._secret = client_secret

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        payload: dict[str, str] | None = None,
        params: dict[str, str | int] | None = None,
        device_poll: bool = False,
    ) -> tuple[bytes, httpx.Headers] | DeviceStatus:
        headers = {
            "trakt-api-version": "2",
            "trakt-api-key": self._client_id,
            "Content-Type": "application/json",
            "User-Agent": f"Tasterr/{version('tasterr')}",
        }
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        base = AUTH_BASE if path.startswith("/oauth/") else API_BASE
        try:
            async with (
                asyncio.timeout(TIMEOUT_SECONDS),
                self._http.stream(
                    method,
                    base + path,
                    headers=headers,
                    json=payload,
                    params=params,
                    timeout=TIMEOUT_SECONDS,
                    follow_redirects=False,
                ) as response,
            ):
                status = response.status_code
                if device_poll:
                    outcomes: dict[int, DeviceStatus] = {
                        400: "pending",
                        429: "slow_down",
                        404: "expired",
                        409: "expired",
                        410: "expired",
                        418: "denied",
                        420: "denied",
                    }
                    if status in outcomes:
                        return outcomes[status]
                if status == 429 or status >= 500:
                    raise UpstreamUnavailable("trakt unavailable")
                if status != 200:
                    raise UpstreamRejected(status)
                data = bytearray()
                async for chunk in response.aiter_bytes():
                    data.extend(chunk)
                    if len(data) > MAX_RESPONSE_BYTES:
                        raise UpstreamUnavailable("trakt response too large")
                return bytes(data), response.headers
        except (httpx.HTTPError, TimeoutError):
            raise UpstreamUnavailable("trakt request failed") from None

    async def device_code(self) -> DeviceCode:
        result = await self._request(
            "POST", "/oauth/device/code", payload={"client_id": self._client_id}
        )
        assert not isinstance(result, str)
        try:
            return DeviceCode.model_validate_json(result[0])
        except ValueError:
            raise UpstreamUnavailable("trakt invalid response") from None

    async def device_token(self, code: str) -> TokenResponse | DeviceStatus:
        result = await self._request(
            "POST",
            "/oauth/device/token",
            payload={"client_id": self._client_id, "code": code},
            device_poll=True,
        )
        if isinstance(result, str):
            return result
        return self._tokens(result[0])

    async def refresh(self, refresh_token: str) -> TokenResponse:
        payload = {
            "refresh_token": refresh_token,
            "client_id": self._client_id,
            "grant_type": "refresh_token",
            "redirect_uri": REDIRECT_URI,
        }
        if self._secret is not None:
            payload["client_secret"] = self._secret
        result = await self._request("POST", "/oauth/token", payload=payload)
        assert not isinstance(result, str)
        return self._tokens(result[0])

    async def revoke(self, token: str) -> None:
        payload = {"client_id": self._client_id, "token": token}
        if self._secret is not None:
            payload["client_secret"] = self._secret
        await self._request("POST", "/oauth/revoke", payload=payload)

    async def user_settings(self, token: str) -> UserSettings:
        result = await self._request("GET", "/users/settings", token=token)
        assert not isinstance(result, str)
        try:
            return UserSettings.model_validate_json(result[0])
        except ValueError:
            raise UpstreamUnavailable("trakt invalid response") from None

    async def last_activities(self, token: str) -> LastActivities:
        result = await self._request("GET", "/sync/last_activities", token=token)
        assert not isinstance(result, str)
        try:
            return LastActivities.model_validate_json(result[0])
        except ValueError:
            raise UpstreamUnavailable("trakt invalid response") from None

    async def history(
        self,
        token: str,
        media_type: HistoryType,
        *,
        page: int = 1,
        limit: int = 250,
        start_at: str | None = None,
    ) -> HistoryPage:
        params: dict[str, str | int] = {"page": page, "limit": limit}
        if start_at is not None:
            params["start_at"] = start_at
        result = await self._request(
            "GET",
            f"/sync/history/{media_type}",
            token=token,
            params=params,
        )
        assert not isinstance(result, str)
        data, headers = result
        try:
            items = _PLAYS.validate_json(data, strict=True)
            count = headers.get("X-Pagination-Page-Count")
            applied_limit = headers.get("X-Pagination-Limit")
            page_count = int(count) if count is not None else None
            page_limit = int(applied_limit) if applied_limit is not None else None
            if (page_count is not None and page_count < 0) or (
                page_limit is not None and page_limit < 1
            ):
                raise ValueError
            return HistoryPage(items, page_count, page_limit)
        except ValueError:
            raise UpstreamUnavailable("trakt invalid response") from None

    @staticmethod
    def _tokens(data: bytes) -> TokenResponse:
        try:
            return TokenResponse.model_validate_json(data)
        except ValueError:
            raise UpstreamUnavailable("trakt invalid response") from None

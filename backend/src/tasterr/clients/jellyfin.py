"""Jellyfin authentication and explicit user-scoped reads, with header-only auth."""

from datetime import datetime
from typing import Literal

import httpx
from pydantic import BaseModel, ConfigDict, Field

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

JELLYFIN_TIMEOUT_SECONDS = 5.0
JELLYFIN_PAGE_SIZE = 100


class JellyfinPolicy(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    is_administrator: bool = Field(alias="IsAdministrator")
    is_disabled: bool = Field(alias="IsDisabled")


class JellyfinUser(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id", pattern=r"^[a-fA-F0-9-]{32,36}$")
    name: str = Field(alias="Name", min_length=1, max_length=4096)
    policy: JellyfinPolicy = Field(alias="Policy")


class JellyfinLogin(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    user: JellyfinUser = Field(alias="User")
    access_token: str = Field(alias="AccessToken", min_length=1, repr=False)


class JellyfinUserData(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    last_played_date: datetime | None = Field(default=None, alias="LastPlayedDate")


class JellyfinItem(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str = Field(alias="Id", pattern=r"^[a-fA-F0-9-]{32,36}$")
    provider_ids: dict[str, str] = Field(default_factory=dict, alias="ProviderIds")
    series_id: str | None = Field(default=None, alias="SeriesId", pattern=r"^[a-fA-F0-9-]{32,36}$")
    user_data: JellyfinUserData | None = Field(default=None, alias="UserData")


class JellyfinItems(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    items: list[JellyfinItem] = Field(alias="Items")
    total_record_count: int = Field(alias="TotalRecordCount", ge=0)


class JellyfinClient:
    def __init__(
        self, http: httpx.AsyncClient, base_url: str, api_key: str, device_id: str
    ) -> None:
        self._http = http
        self._base = base_url.rstrip("/")
        self._key = api_key
        self._device_id = device_id

    def _authorization(self, token: str | None = None) -> dict[str, str]:
        authorization = (
            'MediaBrowser Client="Tasterr", Device="Tasterr", '
            f'DeviceId="{self._device_id}", Version="1"'
        )
        if token is not None:
            escaped = token.replace("\\", "\\\\").replace('"', '\\"')
            authorization += f', Token="{escaped}"'
        return {"Authorization": authorization}

    async def _request(
        self,
        method: str,
        path: str,
        *,
        token: str | None = None,
        params: dict[str, str | int] | None = None,
        payload: dict[str, str] | None = None,
    ) -> httpx.Response:
        try:
            response = await self._http.request(
                method,
                f"{self._base}{path}",
                headers=self._authorization(token),
                params=params,
                json=payload,
                timeout=JELLYFIN_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("jellyfin request failed") from None
        if response.status_code in (502, 503, 504):
            raise UpstreamUnavailable("jellyfin unavailable")
        if response.status_code not in (200, 204):
            raise UpstreamRejected(response.status_code)
        return response

    async def authenticate(self, username: str, password: str) -> JellyfinLogin:
        response = await self._request(
            "POST", "/Users/AuthenticateByName", payload={"Username": username, "Pw": password}
        )
        try:
            return JellyfinLogin.model_validate_json(response.content, strict=True)
        except ValueError:
            raise UpstreamRejected(200) from None

    async def logout(self, token: str) -> None:
        await self._request("POST", "/Sessions/Logout", token=token)

    async def user(self, user_id: str) -> JellyfinUser:
        response = await self._request("GET", "/Users/" + user_id, token=self._key)
        try:
            user = JellyfinUser.model_validate_json(response.content, strict=True)
        except ValueError:
            raise UpstreamRejected(200) from None
        if user.id != user_id:
            raise UpstreamRejected(200)
        return user

    async def played_items(
        self, user_id: str, item_type: Literal["Movie", "Episode"], start_index: int
    ) -> JellyfinItems:
        response = await self._request(
            "GET",
            "/Items",
            token=self._key,
            params={
                "userId": user_id,
                "IncludeItemTypes": item_type,
                "Filters": "IsPlayed",
                "Recursive": "true",
                "Fields": "ProviderIds",
                "SortBy": "DatePlayed",
                "SortOrder": "Descending",
                "StartIndex": start_index,
                "Limit": JELLYFIN_PAGE_SIZE,
            },
        )
        return self._items(response)

    async def series(self, user_id: str, ids: list[str]) -> JellyfinItems:
        if not 1 <= len(ids) <= JELLYFIN_PAGE_SIZE:
            raise ValueError("series batch must contain 1-100 ids")
        response = await self._request(
            "GET",
            "/Items",
            token=self._key,
            params={
                "userId": user_id,
                "Ids": ",".join(ids),
                "Fields": "ProviderIds",
                "Limit": JELLYFIN_PAGE_SIZE,
            },
        )
        return self._items(response)

    @staticmethod
    def _items(response: httpx.Response) -> JellyfinItems:
        try:
            page = JellyfinItems.model_validate_json(response.content, strict=True)
        except ValueError:
            raise UpstreamRejected(200) from None
        if len(page.items) > JELLYFIN_PAGE_SIZE:
            raise UpstreamRejected(200)
        return page

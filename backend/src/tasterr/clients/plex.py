"""Plex account, resource, and PMS reads — the only module that talks to Plex."""

import asyncio
from dataclasses import dataclass
from typing import Annotated, cast
from urllib.parse import quote, urlencode, urlsplit

import httpx
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    field_validator,
)

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

PINS_URL = "https://plex.tv/api/v2/pins"
USER_URL = "https://plex.tv/api/v2/user"
RESOURCES_URL = "https://plex.tv/api/v2/resources"
AUTH_URL = "https://app.plex.tv/auth"
PRODUCT = "Tasterr"
PLEX_TIMEOUT_SECONDS = 5.0
MAX_SERVERS = 4
MAX_CONNECTIONS_PER_SERVER = 6
HISTORY_PAGE_SIZE = 100
HISTORY_MAX_ROWS = 500
HUB_MAX_ITEMS = 50
PositiveInt = Annotated[int, Field(strict=True, gt=0)]


class PlexPin(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: PositiveInt
    code: str


class _PinStatus(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    auth_token: str | None = Field(default=None, alias="authToken")


class PlexCloudAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: PositiveInt
    username: StrictStr


class PlexConnection(BaseModel):
    model_config = ConfigDict(extra="ignore")

    uri: StrictStr
    local: StrictBool = False
    relay: StrictBool = False


class PlexResource(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    client_identifier: StrictStr = Field(alias="clientIdentifier", min_length=1)
    access_token: SecretStr = Field(alias="accessToken")
    owned: StrictBool = False
    provides: StrictStr = ""
    connections: list[PlexConnection] = []


class PlexPmsAccount(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: PositiveInt
    key: StrictInt | StrictStr | None = None
    name: StrictStr = Field(min_length=1)


class PlexGuid(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: StrictStr


class PlexPmsItem(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    account_id: PositiveInt | None = Field(default=None, alias="accountID")
    viewed_at: PositiveInt | None = Field(default=None, alias="viewedAt")
    last_viewed_at: PositiveInt | None = Field(default=None, alias="lastViewedAt")
    grandparent_last_viewed_at: PositiveInt | None = Field(
        default=None, alias="grandparentLastViewedAt"
    )
    parent_last_viewed_at: PositiveInt | None = Field(default=None, alias="parentLastViewedAt")
    media_type: StrictStr = Field(default="", alias="type")
    rating_key: StrictInt | StrictStr | None = Field(default=None, alias="ratingKey")
    grandparent_rating_key: StrictInt | StrictStr | None = Field(
        default=None, alias="grandparentRatingKey"
    )
    parent_index: PositiveInt | None = Field(default=None, alias="parentIndex")
    index: PositiveInt | None = None
    view_offset: int | float | None = Field(default=None, alias="viewOffset")
    duration: int | float | None = None
    guids: list[PlexGuid] = Field(default=[], alias="Guid")

    @field_validator(
        "last_viewed_at",
        "grandparent_last_viewed_at",
        "parent_last_viewed_at",
        mode="before",
    )
    @classmethod
    def validate_optional_timestamp(cls, value: object) -> object:
        return value if type(value) is int and value > 0 else None

    @field_validator("view_offset", "duration", mode="before")
    @classmethod
    def validate_progress_number(cls, value: object) -> object:
        return value if type(value) in (int, float) else None

    @field_validator("rating_key", "grandparent_rating_key", mode="before")
    @classmethod
    def validate_rating_key(cls, value: object) -> object:
        if type(value) is int and value > 0:
            return value
        if isinstance(value, str) and value.isdecimal() and int(value) > 0:
            return value
        return None

    @field_validator("parent_index", "index", mode="before")
    @classmethod
    def validate_episode_coordinate(cls, value: object) -> object:
        return value if type(value) is int and value > 0 else None


class PlexServer(BaseModel):
    model_config = ConfigDict(frozen=True)

    base_url: str
    machine_identifier: str
    access_token: SecretStr
    version: str | None = None


@dataclass(frozen=True)
class PlexServerDiscovery:
    servers: tuple[PlexServer, ...]
    complete: bool


class _Identity(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    machine_identifier: str = Field(alias="machineIdentifier")
    version: str | None = None


class _IdentityEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_container: _Identity = Field(alias="MediaContainer")


class _AccountsContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    accounts: list[object] = Field(default=[], alias="Account")


class _AccountsEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_container: _AccountsContainer = Field(alias="MediaContainer")


class _ItemsContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    offset: int | None = None
    items: list[PlexPmsItem] = Field(default=[], alias="Metadata")


class _ItemsEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_container: _ItemsContainer = Field(alias="MediaContainer")


class _Hub(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    items: list[PlexPmsItem] = Field(default=[], alias="Metadata")


class _HubContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    hubs: list[_Hub] = Field(default=[], alias="Hub")


class _HubEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_container: _HubContainer = Field(alias="MediaContainer")


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
                PINS_URL,
                params={"strong": "true"},
                headers=self._headers(),
                timeout=PLEX_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("plex.tv request failed") from None
        _raise_for_status(response)
        try:
            return PlexPin.model_validate(response.json())
        except ValueError as error:
            raise UpstreamUnavailable("unexpected plex.tv response shape") from error

    async def poll_pin(self, pin_id: int) -> str | None:
        """The Plex auth token once the user has approved the PIN, else None.
        plex.tv answers 404 for expired or unknown PINs."""
        try:
            response = await self._http.get(
                f"{PINS_URL}/{pin_id}",
                headers=self._headers(),
                timeout=PLEX_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("plex.tv request failed") from None
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


class PlexMediaClient:
    def __init__(self, http: httpx.AsyncClient, client_identifier: str) -> None:
        self._http = http
        self._client_identifier = client_identifier

    def _headers(self, token: str | None = None) -> dict[str, str]:
        headers = {
            "Accept": "application/json",
            "X-Plex-Product": PRODUCT,
            "X-Plex-Client-Identifier": self._client_identifier,
        }
        if token is not None:
            headers["X-Plex-Token"] = token
        return headers

    async def account(self, account_token: str) -> PlexCloudAccount:
        payload = await self._cloud_json(USER_URL, account_token)
        try:
            return PlexCloudAccount.model_validate(payload)
        except ValidationError as error:
            raise UpstreamUnavailable("unexpected plex.tv response shape") from error

    async def servers(self, account_token: str) -> list[PlexServer]:
        return list((await self.discover_servers(account_token)).servers)

    async def discover_servers(self, account_token: str) -> PlexServerDiscovery:
        payload = await self._cloud_json(
            RESOURCES_URL,
            account_token,
            params={"includeHttps": "1", "includeRelay": "1", "includeIPv6": "1"},
        )
        if not isinstance(payload, list):
            raise UpstreamUnavailable("unexpected plex.tv response shape")

        resources: list[PlexResource] = []
        for item in cast("list[object]", payload):
            try:
                resource = PlexResource.model_validate(item)
            except ValidationError:
                continue
            if "server" in resource.provides.split(","):
                resources.append(resource)
        resources.sort(key=lambda item: (not item.owned, item.client_identifier))

        tasks = [
            asyncio.create_task(self._validated_server(resource))
            for resource in resources[:MAX_SERVERS]
        ]
        try:
            validated = await asyncio.gather(*tasks)
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        servers = [server for server in validated if server is not None]
        return PlexServerDiscovery(
            servers=tuple(servers),
            complete=len(servers) == min(len(resources), MAX_SERVERS),
        )

    async def _pms_account_rows(self, server: PlexServer) -> list[object]:
        payload = await self._pms_json(server, "/accounts")
        try:
            return _AccountsEnvelope.model_validate(payload).media_container.accounts
        except ValidationError as error:
            raise UpstreamUnavailable("unexpected Plex Media Server response shape") from error

    async def resolve_account_id(self, server: PlexServer, account: PlexCloudAccount) -> int:
        try:
            rows = await self._pms_account_rows(server)
        except UpstreamRejected as error:
            if error.status_code == 403:
                return account.id
            raise
        accounts: list[PlexPmsAccount] = []
        for row in rows:
            try:
                accounts.append(PlexPmsAccount.model_validate(row))
            except ValidationError as error:
                if _could_match_account(row, account):
                    raise UpstreamUnavailable("Plex account identity was malformed") from error
        direct = [
            candidate
            for candidate in accounts
            if candidate.id == account.id or _numeric_key(candidate.key) == account.id
        ]
        named = [
            candidate
            for candidate in accounts
            if account.username and candidate.name.casefold() == account.username.casefold()
        ]
        if len(direct) > 1 or len(named) > 1:
            raise UpstreamUnavailable("Plex account identity was ambiguous")
        if direct:
            if named and named[0].id != direct[0].id:
                raise UpstreamUnavailable("Plex account identity was conflicting")
            return direct[0].id
        if len(named) == 1:
            return named[0].id
        raise UpstreamUnavailable("Plex account identity was unavailable")

    async def history(
        self,
        server: PlexServer,
        account_id: int,
        *,
        viewed_after: int,
        viewed_before: int,
    ) -> list[PlexPmsItem]:
        if account_id <= 0 or viewed_after < 0 or viewed_before < viewed_after:
            raise ValueError("invalid Plex history bounds")
        items: list[PlexPmsItem] = []
        for start in range(0, HISTORY_MAX_ROWS, HISTORY_PAGE_SIZE):
            payload = await self._pms_json(
                server,
                "/status/sessions/history/all",
                params={
                    "accountID": str(account_id),
                    "sort": "viewedAt:desc",
                    "viewedAt>": str(viewed_after),
                    "viewedAt<": str(viewed_before),
                },
                headers={
                    "X-Plex-Container-Start": str(start),
                    "X-Plex-Container-Size": str(HISTORY_PAGE_SIZE),
                },
            )
            try:
                container = _ItemsEnvelope.model_validate(payload).media_container
            except ValidationError as error:
                raise UpstreamUnavailable("unexpected Plex Media Server response shape") from error
            page = container.items
            if container.offset is not None and container.offset != start:
                raise UpstreamUnavailable("unexpected Plex history pagination")
            if len(page) > HISTORY_PAGE_SIZE:
                raise UpstreamUnavailable("unexpected Plex history page size")
            if any(item.account_id != account_id for item in page):
                raise UpstreamUnavailable("Plex history account mismatch")
            timestamps = [item.viewed_at for item in (*items, *page)]
            if any(
                value is None or value < viewed_after or value > viewed_before
                for value in timestamps
            ):
                raise UpstreamUnavailable("unexpected Plex history window")
            if timestamps != sorted(timestamps, reverse=True, key=lambda value: value or 0):
                raise UpstreamUnavailable("unexpected Plex history ordering")
            items.extend(page)
            if len(page) < HISTORY_PAGE_SIZE:
                break
        return items

    async def continue_watching(self, server: PlexServer) -> list[PlexPmsItem]:
        payload = await self._pms_json(
            server,
            "/hubs/continueWatching",
            headers={
                "X-Plex-Container-Start": "0",
                "X-Plex-Container-Size": str(HUB_MAX_ITEMS),
            },
        )
        try:
            hubs = _HubEnvelope.model_validate(payload).media_container.hubs
        except ValidationError as error:
            raise UpstreamUnavailable("unexpected Plex Media Server response shape") from error
        return [item for hub in hubs for item in hub.items][:HUB_MAX_ITEMS]

    async def metadata(self, server: PlexServer, rating_key: int | str) -> PlexPmsItem | None:
        normalized_key = str(rating_key)
        if not normalized_key.isdecimal() or int(normalized_key) <= 0:
            return None
        payload = await self._pms_json(
            server,
            f"/library/metadata/{quote(normalized_key, safe='')}",
            params={"includeGuids": "1"},
        )
        try:
            items = _ItemsEnvelope.model_validate(payload).media_container.items
        except ValidationError as error:
            raise UpstreamUnavailable("unexpected Plex Media Server response shape") from error
        if not items:
            return None
        item = items[0]
        if str(item.rating_key) != normalized_key:
            raise UpstreamUnavailable("unexpected Plex metadata identity")
        return item

    async def _cloud_json(
        self,
        url: str,
        account_token: str,
        *,
        params: dict[str, str] | None = None,
    ) -> object:
        try:
            response = await self._http.get(
                url,
                params=params,
                headers=self._headers(account_token),
                timeout=PLEX_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("plex.tv request failed") from None
        _raise_for_status(response)
        try:
            return response.json()
        except ValueError as error:
            raise UpstreamUnavailable("unexpected plex.tv response shape") from error

    async def _pms_json(
        self,
        server: PlexServer,
        path: str,
        *,
        params: dict[str, str] | None = None,
        headers: dict[str, str] | None = None,
    ) -> object:
        request_headers = self._headers(server.access_token.get_secret_value())
        if headers is not None:
            request_headers.update(headers)
        try:
            response = await self._http.get(
                f"{server.base_url}{path}",
                params=params,
                headers=request_headers,
                timeout=PLEX_TIMEOUT_SECONDS,
                follow_redirects=False,
            )
        except httpx.HTTPError:
            raise UpstreamUnavailable("Plex Media Server request failed") from None
        if 300 <= response.status_code < 400 or response.status_code >= 500:
            raise UpstreamUnavailable("Plex Media Server request failed")
        if response.status_code >= 400:
            raise UpstreamRejected(response.status_code)
        try:
            return response.json()
        except ValueError as error:
            raise UpstreamUnavailable("unexpected Plex Media Server response shape") from error

    async def _validated_server(self, resource: PlexResource) -> PlexServer | None:
        connections = [
            connection
            for connection in sorted(
                resource.connections,
                key=lambda item: (
                    2 if item.relay else 0 if item.local else 1,
                    item.uri,
                ),
            )
            if _validated_connection_url(connection.uri) is not None
        ][:MAX_CONNECTIONS_PER_SERVER]

        async def validate(connection: PlexConnection) -> PlexServer | None:
            base_url = _validated_connection_url(connection.uri)
            if base_url is None:
                return None
            try:
                response = await self._http.get(
                    f"{base_url}/identity",
                    headers=self._headers(),
                    timeout=PLEX_TIMEOUT_SECONDS,
                    follow_redirects=False,
                )
            except httpx.HTTPError:
                return None
            if response.status_code != 200:
                return None
            try:
                identity = _IdentityEnvelope.model_validate(response.json()).media_container
            except (ValueError, ValidationError):
                return None
            if identity.machine_identifier != resource.client_identifier:
                return None
            return PlexServer(
                base_url=base_url,
                machine_identifier=resource.client_identifier,
                access_token=resource.access_token,
                version=identity.version,
            )

        tasks = [asyncio.create_task(validate(connection)) for connection in connections]
        try:
            for task in tasks:
                server = await task
                if server is not None:
                    return server
            return None
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)


def _validated_connection_url(uri: str) -> str | None:
    try:
        parsed = urlsplit(uri)
        port = parsed.port
    except ValueError:
        return None
    host = (parsed.hostname or "").lower()
    if (
        parsed.scheme != "https"
        or not host.endswith(".plex.direct")
        or host == ".plex.direct"
        or port is None
        or port < 1
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in ("", "/")
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"https://{host}:{port}"


def _numeric_key(value: int | str | None) -> int | None:
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _could_match_account(row: object, account: PlexCloudAccount) -> bool:
    if not isinstance(row, dict):
        return False
    values = cast("dict[str, object]", row)
    raw_id = values.get("id")
    if _candidate_id(raw_id) == account.id or _candidate_id(values.get("key")) == account.id:
        return True
    if type(raw_id) is int and raw_id <= 0:
        return False
    name = values.get("name")
    return bool(
        account.username
        and isinstance(name, str)
        and name.casefold() == account.username.casefold()
    )


def _candidate_id(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdecimal():
        return int(value)
    return None


def _raise_for_status(response: httpx.Response) -> None:
    if 300 <= response.status_code < 400:
        raise UpstreamUnavailable("plex.tv returned a redirect")
    if response.status_code >= 500:
        raise UpstreamUnavailable(f"plex.tv returned {response.status_code}")
    if response.status_code >= 400:
        raise UpstreamRejected(response.status_code)

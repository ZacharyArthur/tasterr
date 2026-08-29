import asyncio
import json
from collections.abc import Callable

import httpx
import pytest
from pydantic import SecretStr

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import (
    PlexAuthClient,
    PlexCloudAccount,
    PlexMediaClient,
    PlexServer,
)

CLIENT_ID = "11111111-2222-5333-8444-555555555555"

# Shape from the auth spike (docs/SEERR-AUTH-SPIKE.md), values redacted.
PIN_CREATED = {"id": 123456, "code": "abcd1234efgh", "product": "Tasterr", "trusted": False}
PIN_UNCLAIMED = {**PIN_CREATED, "authToken": None}
PIN_CLAIMED = {**PIN_CREATED, "authToken": "plex-auth-token"}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> PlexAuthClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PlexAuthClient(http, CLIENT_ID)


def _media_client(handler: Callable[[httpx.Request], httpx.Response]) -> PlexMediaClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PlexMediaClient(http, CLIENT_ID)


def _resource(
    machine_id: str,
    *uris: str,
    owned: bool = False,
    access_token: str = "resource-token",
) -> dict[str, object]:
    return {
        "clientIdentifier": machine_id,
        "accessToken": access_token,
        "owned": owned,
        "provides": "server",
        "connections": [
            {"uri": uri, "local": "local" in uri, "relay": "relay" in uri} for uri in uris
        ],
    }


def _identity(machine_id: str) -> httpx.Response:
    return httpx.Response(
        200,
        json={"MediaContainer": {"machineIdentifier": machine_id, "version": "1.2.3"}},
    )


def _server() -> PlexServer:
    return PlexServer(
        base_url="https://machine.plex.direct:32400",
        machine_identifier="machine",
        access_token=SecretStr("resource-token"),
        version="1.2.3",
    )


def _history_row(
    account_id: object, viewed_at: object, *, media_type: str = "movie"
) -> dict[str, object]:
    return {
        "accountID": account_id,
        "viewedAt": viewed_at,
        "type": media_type,
        "ratingKey": str(viewed_at),
        "unexpected": "ignored",
    }


async def test_create_pin_sends_identity_headers() -> None:
    seen: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["product"] = request.headers["x-plex-product"]
        seen["client_id"] = request.headers["x-plex-client-identifier"]
        seen["accept"] = request.headers["accept"]
        return httpx.Response(201, json=PIN_CREATED)

    pin = await _client(handler).create_pin()

    assert pin.id == 123456
    assert pin.code == "abcd1234efgh"
    assert seen["url"] == "https://plex.tv/api/v2/pins?strong=true"
    assert seen["product"] == "Tasterr"
    assert seen["client_id"] == CLIENT_ID
    assert seen["accept"] == "application/json"


async def test_poll_unclaimed_pin_returns_none() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v2/pins/123456"
        return httpx.Response(200, json=PIN_UNCLAIMED)

    assert await _client(handler).poll_pin(123456) is None


async def test_poll_claimed_pin_returns_token() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=PIN_CLAIMED)

    assert await _client(handler).poll_pin(123456) == "plex-auth-token"


async def test_poll_expired_pin_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"errors": [{"code": 1020, "message": "not found"}]})

    with pytest.raises(UpstreamRejected) as excinfo:
        await _client(handler).poll_pin(123456)
    assert excinfo.value.status_code == 404


async def test_server_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).create_pin()


async def test_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).create_pin()


async def test_malformed_body_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(201, json={"unexpected": True})

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).create_pin()


async def test_no_browser_headers_are_forwarded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(201, json=PIN_CREATED)

    await _client(handler).create_pin()


def test_auth_url_is_built_from_validated_parts() -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    client = PlexAuthClient(http, CLIENT_ID)

    url = client.auth_url("abcd1234efgh")

    assert url.startswith("https://app.plex.tv/auth#?")
    assert f"clientID={CLIENT_ID}" in url
    assert "code=abcd1234efgh" in url
    assert "product%5D=Tasterr" in url


def test_pin_fixture_shapes_stay_json_serializable() -> None:
    # Guards against fixture drift breaking the MockTransport contract tests.
    for fixture in (PIN_CREATED, PIN_UNCLAIMED, PIN_CLAIMED):
        json.dumps(fixture)


async def test_media_account_uses_header_only_token() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://plex.tv/api/v2/user"
        assert request.headers["x-plex-token"] == "account-token"
        assert "account-token" not in str(request.url)
        return httpx.Response(200, json={"id": 42, "username": "member", "ignored": True})

    account = await _media_client(handler).account("account-token")

    assert account.id == 42
    assert account.username == "member"


@pytest.mark.parametrize("account_id", [True, "42"])
async def test_media_account_rejects_coercive_ids(account_id: object) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": account_id, "username": "member"})

    with pytest.raises(UpstreamUnavailable, match=r"unexpected plex\.tv response shape"):
        await _media_client(handler).account("account-token")


async def test_servers_order_owned_then_machine_and_connections_local_direct_relay() -> None:
    attempts: list[str] = []
    resources = [
        _resource("z-shared", "https://z-shared.plex.direct:32400"),
        _resource(
            "b-owned",
            "https://relay-b-owned.plex.direct:443",
            "https://direct-b-owned.plex.direct:32400",
            "https://local-b-owned.plex.direct:32400",
            owned=True,
        ),
        _resource("a-owned", "https://a-owned.plex.direct:32400", owned=True),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            assert request.headers["x-plex-token"] == "account-token"
            return httpx.Response(200, json=resources)
        attempts.append(request.url.host or "")
        assert "x-plex-token" not in request.headers
        machine_id = (request.url.host or "").split(".", 1)[0]
        if machine_id == "local-b-owned":
            machine_id = "b-owned"
        return _identity(machine_id)

    servers = await _media_client(handler).servers("account-token")

    assert [server.machine_identifier for server in servers] == [
        "a-owned",
        "b-owned",
        "z-shared",
    ]
    assert set(attempts) == {
        "a-owned.plex.direct",
        "local-b-owned.plex.direct",
        "direct-b-owned.plex.direct",
        "relay-b-owned.plex.direct",
        "z-shared.plex.direct",
    }
    assert all(server.version == "1.2.3" for server in servers)


async def test_server_selection_is_capped_at_four() -> None:
    resources = [
        _resource(f"machine-{index}", f"https://machine-{index}.plex.direct:32400")
        for index in range(5)
    ]
    identities = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal identities
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=resources)
        identities += 1
        return _identity((request.url.host or "").split(".", 1)[0])

    servers = await _media_client(handler).servers("account-token")

    assert len(servers) == 4
    assert identities == 4


async def test_connection_attempts_are_capped_at_six() -> None:
    uris = tuple(f"https://server-{index}.plex.direct:32400" for index in range(7))
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=[_resource("machine", *uris)])
        attempts += 1
        if request.url.host == "server-6.plex.direct":
            return _identity("machine")
        raise httpx.ConnectError("unavailable", request=request)

    assert await _media_client(handler).servers("account-token") == []
    assert attempts == 6


async def test_invalid_connections_do_not_consume_the_probe_budget() -> None:
    uris = (
        *(f"http://bad-{index}.plex.direct:32400" for index in range(6)),
        "https://healthy.plex.direct:32400",
    )
    attempts = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=[_resource("machine", *uris)])
        attempts += 1
        return _identity("machine")

    servers = await _media_client(handler).servers("account-token")

    assert [server.machine_identifier for server in servers] == ["machine"]
    assert attempts == 1


async def test_connection_fallbacks_are_probed_concurrently() -> None:
    uris = tuple(f"https://server-{index}.plex.direct:32400" for index in range(6))
    started: set[str] = set()
    all_started = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=[_resource("machine", *uris)])
        host = request.url.host or ""
        started.add(host)
        if len(started) == 6:
            all_started.set()
        await all_started.wait()
        if host == "server-5.plex.direct":
            return _identity("machine")
        raise httpx.ConnectError("unavailable", request=request)

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    servers = await asyncio.wait_for(PlexMediaClient(http, CLIENT_ID).servers("account-token"), 0.5)

    assert [server.machine_identifier for server in servers] == ["machine"]
    assert len(started) == 6


async def test_slower_preferred_connection_wins_over_faster_relay() -> None:
    relay_finished = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(
                200,
                json=[
                    _resource(
                        "machine",
                        "https://local-machine.plex.direct:32400",
                        "https://relay-machine.plex.direct:443",
                    )
                ],
            )
        if request.url.host == "local-machine.plex.direct":
            await relay_finished.wait()
            return _identity("machine")
        relay_finished.set()
        return _identity("machine")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    servers = await asyncio.wait_for(PlexMediaClient(http, CLIENT_ID).servers("token"), 0.5)

    assert servers[0].base_url == "https://local-machine.plex.direct:32400"


async def test_connection_winner_cancels_pending_lower_priority_probe() -> None:
    relay_started = asyncio.Event()
    relay_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(
                200,
                json=[
                    _resource(
                        "machine",
                        "https://local-machine.plex.direct:32400",
                        "https://relay-machine.plex.direct:443",
                    )
                ],
            )
        if request.url.host == "local-machine.plex.direct":
            await relay_started.wait()
            return _identity("machine")
        relay_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            relay_cancelled.set()
            raise
        raise AssertionError("unreachable")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    servers = await asyncio.wait_for(PlexMediaClient(http, CLIENT_ID).servers("token"), 0.5)

    assert servers[0].base_url == "https://local-machine.plex.direct:32400"
    assert relay_cancelled.is_set()


async def test_server_discovery_cancels_siblings_on_unexpected_error() -> None:
    slow_started = asyncio.Event()
    slow_cancelled = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(
                200,
                json=[
                    _resource("bad", "https://bad.plex.direct:32400"),
                    _resource("slow", "https://slow.plex.direct:32400"),
                ],
            )
        if request.url.host == "bad.plex.direct":
            await slow_started.wait()
            raise RuntimeError("client closed")
        slow_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            slow_cancelled.set()
            raise
        raise AssertionError("unreachable")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    with pytest.raises(RuntimeError, match="client closed"):
        await PlexMediaClient(http, CLIENT_ID).servers("token")

    assert slow_cancelled.is_set()


@pytest.mark.parametrize(
    "uri",
    [
        "http://machine.plex.direct:32400",
        "https://example.com:32400",
        "https://user:pass@machine.plex.direct:32400",
        "https://machine.plex.direct",
        "https://machine.plex.direct:32400/path",
        "https://machine.plex.direct:32400?token=secret",
        "https://machine.plex.direct:32400#fragment",
        "https://machine.plex.direct:0",
        "https://machine.plex.direct:99999",
    ],
)
async def test_hostile_connections_are_rejected_without_a_request(uri: str) -> None:
    identity_requested = False

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal identity_requested
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=[_resource("machine", uri)])
        identity_requested = True
        return _identity("machine")

    assert await _media_client(handler).servers("account-token") == []
    assert identity_requested is False


@pytest.mark.parametrize("failure", ["certificate", "timeout"])
async def test_tls_or_timeout_failure_skips_the_connection(failure: str) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(
                200,
                json=[_resource("machine", "https://machine.plex.direct:32400")],
            )
        if failure == "certificate":
            raise httpx.ConnectError("certificate verify failed", request=request)
        raise httpx.ConnectTimeout("timed out", request=request)

    assert await _media_client(handler).servers("account-token") == []


async def test_identity_redirect_is_not_followed() -> None:
    requests: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(str(request.url))
        if request.url.host == "plex.tv":
            return httpx.Response(
                200,
                json=[_resource("machine", "https://machine.plex.direct:32400")],
            )
        return httpx.Response(302, headers={"location": "https://other.plex.direct:32400"})

    assert await _media_client(handler).servers("account-token") == []
    assert len(requests) == 2


async def test_malformed_media_shapes_are_generic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v2/user":
            return httpx.Response(200, json={"id": "not-an-id"})
        return httpx.Response(200, json={"not": "a resource list"})

    client = _media_client(handler)
    with pytest.raises(UpstreamUnavailable, match=r"unexpected plex\.tv response shape"):
        await client.account("account-token")
    with pytest.raises(UpstreamUnavailable, match=r"unexpected plex\.tv response shape"):
        await client.servers("account-token")


async def test_tokens_do_not_leak_to_identity_url_or_repr() -> None:
    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_urls.append(str(request.url))
        if request.url.host == "plex.tv":
            assert request.headers["x-plex-token"] == "account-token-sentinel"
            return httpx.Response(
                200,
                json=[
                    _resource(
                        "machine",
                        "https://machine.plex.direct:32400",
                        access_token="resource-token-sentinel",
                    )
                ],
            )
        assert "x-plex-token" not in request.headers
        return _identity("machine")

    servers = await _media_client(handler).servers("account-token-sentinel")

    assert all("token-sentinel" not in url for url in seen_urls)
    assert "resource-token-sentinel" not in repr(servers)


async def test_one_bad_server_does_not_hide_a_valid_sibling() -> None:
    resources = [
        _resource("bad", "https://bad.plex.direct:32400", owned=True),
        _resource("good", "https://good.plex.direct:32400"),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "plex.tv":
            return httpx.Response(200, json=resources)
        if request.url.host == "bad.plex.direct":
            return _identity("wrong-machine")
        return _identity("good")

    discovery = await _media_client(handler).discover_servers("account-token")

    assert [server.machine_identifier for server in discovery.servers] == ["good"]
    assert discovery.complete is False


@pytest.mark.parametrize(
    ("cloud", "accounts", "expected"),
    [
        (
            PlexCloudAccount(id=42, username="managed"),
            [{"id": 42, "key": "42", "name": "different"}],
            42,
        ),
        (
            PlexCloudAccount(id=999, username="OwnerName"),
            [
                {"id": 0, "key": "0", "name": "system"},
                {"id": 1, "key": "1", "name": "ownername"},
            ],
            1,
        ),
    ],
)
async def test_pms_account_resolution(
    cloud: PlexCloudAccount, accounts: list[dict[str, object]], expected: int
) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/accounts"
        assert request.headers["x-plex-token"] == "resource-token"
        assert "resource-token" not in str(request.url)
        return httpx.Response(200, json={"MediaContainer": {"Account": accounts}})

    assert await _media_client(handler).resolve_account_id(_server(), cloud) == expected


async def test_pms_account_resolution_uses_cloud_id_only_when_accounts_are_forbidden() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    cloud = PlexCloudAccount(id=42, username="managed")

    assert await _media_client(handler).resolve_account_id(_server(), cloud) == 42


async def test_pms_account_resolution_rejects_other_account_endpoint_failures() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(401)

    with pytest.raises(UpstreamRejected) as excinfo:
        await _media_client(handler).resolve_account_id(
            _server(), PlexCloudAccount(id=42, username="managed")
        )

    assert excinfo.value.status_code == 401


@pytest.mark.parametrize(
    "accounts",
    [
        [],
        [
            {"id": 1, "name": "OWNER"},
            {"id": 2, "name": "owner"},
        ],
        [
            {"id": 42, "name": "someone-else"},
            {"id": 7, "name": "owner"},
        ],
    ],
)
async def test_pms_account_resolution_fails_closed(accounts: list[dict[str, object]]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {"Account": accounts}})

    with pytest.raises(UpstreamUnavailable, match="Plex account identity"):
        await _media_client(handler).resolve_account_id(
            _server(), PlexCloudAccount(id=42, username="owner")
        )


async def test_pms_account_resolution_ignores_only_unrelated_malformed_rows() -> None:
    rows: list[object] = [
        {"id": "unrelated"},
        {"id": 42, "name": "owner"},
    ]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {"Account": rows}})

    assert (
        await _media_client(handler).resolve_account_id(
            _server(), PlexCloudAccount(id=42, username="owner")
        )
        == 42
    )


@pytest.mark.parametrize("candidate_id", ["42", 42.0])
async def test_pms_account_resolution_rejects_malformed_possible_candidates(
    candidate_id: object,
) -> None:
    rows = [{"id": candidate_id}, {"id": 7, "name": "owner"}]

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {"Account": rows}})

    with pytest.raises(UpstreamUnavailable, match="identity was malformed"):
        await _media_client(handler).resolve_account_id(
            _server(), PlexCloudAccount(id=42, username="owner")
        )


async def test_history_is_filtered_ordered_and_paged() -> None:
    starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/status/sessions/history/all"
        assert request.url.params["accountID"] == "42"
        assert request.url.params["sort"] == "viewedAt:desc"
        assert request.url.params["viewedAt>="] == "1000"
        assert request.url.params["viewedAt<="] == "2000"
        start = int(request.headers["x-plex-container-start"])
        starts.append(start)
        count = 100 if start == 0 else 1
        rows = [_history_row(42, 2000 - start - index) for index in range(count)]
        return httpx.Response(
            200,
            json={"MediaContainer": {"offset": start, "Metadata": rows}},
        )

    rows = await _media_client(handler).history(
        _server(), 42, viewed_after=1000, viewed_before=2000
    )

    assert len(rows) == 101
    assert starts == [0, 100]
    assert all(row.account_id == 42 for row in rows)
    timestamps = [row.viewed_at or 0 for row in rows]
    assert timestamps == sorted(timestamps, reverse=True)


async def test_history_stops_at_five_hundred_raw_rows() -> None:
    starts: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.headers["x-plex-container-start"])
        starts.append(start)
        rows = [_history_row(42, 1000 - start - index) for index in range(100)]
        return httpx.Response(200, json={"MediaContainer": {"offset": start, "Metadata": rows}})

    rows = await _media_client(handler).history(_server(), 42, viewed_after=0, viewed_before=2000)

    assert len(rows) == 500
    assert starts == [0, 100, 200, 300, 400]


@pytest.mark.parametrize(
    "row",
    [
        {"viewedAt": 100, "type": "movie", "ratingKey": "1"},
        _history_row(99, 100),
    ],
)
async def test_history_rejects_missing_or_mismatched_account(row: dict[str, object]) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {"offset": 0, "Metadata": [row]}})

    with pytest.raises(UpstreamUnavailable, match="account mismatch"):
        await _media_client(handler).history(_server(), 42, viewed_after=0, viewed_before=2000)


@pytest.mark.parametrize(
    "row",
    [
        _history_row(True, 100),
        _history_row("42", 100),
        _history_row(42, True),
        _history_row(42, "100"),
    ],
)
async def test_history_rejects_coercive_identity_and_timestamp_values(
    row: dict[str, object],
) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"MediaContainer": {"offset": 0, "Metadata": [row]}})

    with pytest.raises(UpstreamUnavailable):
        await _media_client(handler).history(_server(), 42, viewed_after=0, viewed_before=2000)


@pytest.mark.parametrize("viewed_at", [999, 2001])
async def test_history_rejects_rows_outside_the_requested_window(viewed_at: int) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"MediaContainer": {"offset": 0, "Metadata": [_history_row(42, viewed_at)]}},
        )

    with pytest.raises(UpstreamUnavailable, match="history window"):
        await _media_client(handler).history(_server(), 42, viewed_after=1000, viewed_before=2000)


async def test_history_rejects_wrong_offset_and_order() -> None:
    responses = [
        {"MediaContainer": {"offset": 1, "Metadata": [_history_row(42, 100)]}},
        {
            "MediaContainer": {
                "offset": 0,
                "Metadata": [_history_row(42, 100), _history_row(42, 101)],
            }
        },
    ]

    def handler_for(current: object) -> Callable[[httpx.Request], httpx.Response]:
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(200, json=current)

        return handler

    for payload in responses:
        client = _media_client(handler_for(payload))
        with pytest.raises(UpstreamUnavailable):
            await client.history(_server(), 42, viewed_after=0, viewed_before=2000)


async def test_history_rejects_cross_page_ordering() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        start = int(request.headers["x-plex-container-start"])
        rows = (
            [_history_row(42, 1000 - index) for index in range(100)]
            if start == 0
            else [_history_row(42, 1100)]
        )
        return httpx.Response(
            200,
            json={"MediaContainer": {"offset": start, "Metadata": rows}},
        )

    with pytest.raises(UpstreamUnavailable, match="history ordering"):
        await _media_client(handler).history(_server(), 42, viewed_after=0, viewed_before=2000)


async def test_continue_watching_reads_nested_hub_and_caps_at_fifty() -> None:
    metadata = [
        {
            "type": "episode",
            "ratingKey": str(index + 1),
            "grandparentRatingKey": "500",
            "lastViewedAt": 2000 - index,
            "viewOffset": 5,
            "duration": 8,
            "parentIndex": 2,
            "index": 4,
            "unexpected": True,
        }
        for index in range(60)
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/hubs/continueWatching"
        assert request.headers["x-plex-container-size"] == "50"
        return httpx.Response(
            200,
            json={"MediaContainer": {"Hub": [{"Metadata": metadata}], "ignored": True}},
        )

    items = await _media_client(handler).continue_watching(_server())

    assert len(items) == 50
    assert items[0].last_viewed_at == 2000
    assert items[0].grandparent_rating_key == "500"
    assert items[0].parent_index == 2
    assert items[0].index == 4


async def test_continue_watching_drops_coercive_optional_values() -> None:
    row = {
        "type": "episode",
        "ratingKey": True,
        "grandparentRatingKey": 1.0,
        "lastViewedAt": "100",
        "grandparentLastViewedAt": 0,
        "parentLastViewedAt": 1.5,
        "viewOffset": "5",
        "duration": True,
        "parentIndex": "2",
        "index": True,
    }

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"MediaContainer": {"Hub": [{"Metadata": [row]}]}},
        )

    item = (await _media_client(handler).continue_watching(_server()))[0]

    assert item.rating_key is None
    assert item.grandparent_rating_key is None
    assert item.last_viewed_at is None
    assert item.grandparent_last_viewed_at is None
    assert item.parent_last_viewed_at is None
    assert item.view_offset is None
    assert item.duration is None
    assert item.parent_index is None
    assert item.index is None


async def test_metadata_requests_guid_expansion_for_movie_and_episode() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.url.path)
        assert request.url.params["includeGuids"] == "1"
        key = request.url.path.rsplit("/", 1)[-1]
        media_type = "movie" if key == "10" else "show"
        return httpx.Response(
            200,
            json={
                "MediaContainer": {
                    "Metadata": [
                        {
                            "type": media_type,
                            "ratingKey": key,
                            "Guid": [{"id": f"tmdb://{key}"}, {"id": "imdb://ignored"}],
                        }
                    ]
                }
            },
        )

    client = _media_client(handler)
    movie = await client.metadata(_server(), 10)
    show = await client.metadata(_server(), "20")

    assert movie is not None and movie.guids[0].id == "tmdb://10"
    assert show is not None and show.media_type == "show"
    assert seen == ["/library/metadata/10", "/library/metadata/20"]


async def test_invalid_metadata_key_performs_no_request() -> None:
    requested = False

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal requested
        requested = True
        return httpx.Response(500)

    assert await _media_client(handler).metadata(_server(), "../secret") is None
    assert requested is False


async def test_metadata_rejects_a_mismatched_echoed_rating_key() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "MediaContainer": {"Metadata": [{"type": "movie", "ratingKey": "11", "Guid": []}]}
            },
        )

    with pytest.raises(UpstreamUnavailable, match="metadata identity"):
        await _media_client(handler).metadata(_server(), "10")

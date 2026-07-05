import json
from collections.abc import Callable

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexAuthClient

CLIENT_ID = "11111111-2222-5333-8444-555555555555"

# Shape from the auth spike (docs/SEERR-AUTH-SPIKE.md), values redacted.
PIN_CREATED = {"id": 123456, "code": "abcd1234efgh", "product": "Tasterr", "trusted": False}
PIN_UNCLAIMED = {**PIN_CREATED, "authToken": None}
PIN_CLAIMED = {**PIN_CREATED, "authToken": "plex-auth-token"}


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> PlexAuthClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return PlexAuthClient(http, CLIENT_ID)


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

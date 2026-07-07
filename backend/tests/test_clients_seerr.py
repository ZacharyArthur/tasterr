import json
from collections.abc import Callable

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import SeerrAuthClient, SeerrUser

BASE_URL = "http://seerr:5055"

# Shape from the auth spike (docs/SEERR-AUTH-SPIKE.md) against Seerr 3.3.0,
# values redacted. Unknown fields must be ignored, not break parsing.
USER_FIXTURE = {
    "id": 1,
    "displayName": "Viewer",
    "plexUsername": "plex-viewer",
    "email": "owner@example.com",
    "avatar": "https://plex.tv/users/abc/avatar",
    "permissions": 2,
    "movieQuotaLimit": None,
    "createdAt": "2024-01-01T00:00:00.000Z",
}
COOKIE_HEADER = "connect.sid=s%3Aredacted.sig; Path=/; HttpOnly; SameSite=Lax"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> SeerrAuthClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SeerrAuthClient(http, BASE_URL)


async def test_login_plex_returns_user_and_cookie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE_URL}/api/v1/auth/plex"
        assert json.loads(request.read()) == {"authToken": "plex-token"}
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    login = await _client(handler).login_plex("plex-token")

    assert login.user.id == 1
    assert login.user.permissions == 2
    assert login.user.resolved_display_name == "Viewer"
    assert login.cookie == "connect.sid=s%3Aredacted.sig"


async def test_login_local_forwards_credentials_verbatim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/local"
        assert json.loads(request.read()) == {"email": "a@b.c", "password": "hunter2"}
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    login = await _client(handler).login_local("a@b.c", "hunter2")

    assert login.user.id == 1


async def test_rejection_is_typed_with_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": 403, "error": "You do not have permission"})

    with pytest.raises(UpstreamRejected) as excinfo:
        await _client(handler).login_local("a@b.c", "wrong")
    assert excinfo.value.status_code == 403


async def test_server_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_transport_error_drops_cause_and_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _client(handler).login_plex("plex-token")

    # The internal Seerr URL rides in the request the httpx error carries; the
    # fixed message and dropped __cause__ keep it out of both the message and the
    # exception chain an error tracker would capture.
    assert BASE_URL not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_missing_session_cookie_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=USER_FIXTURE)  # no Set-Cookie

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_unexpected_shape_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"totally": "unexpected"}, headers={"set-cookie": COOKIE_HEADER}
        )

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_no_browser_headers_are_forwarded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        assert "x-api-key" not in request.headers  # admin key never rides user flows
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    await _client(handler).login_plex("plex-token")


def test_display_name_fallback_chain() -> None:
    assert SeerrUser(id=9).resolved_display_name == "user-9"
    assert SeerrUser(id=9, email="e@x.y").resolved_display_name == "e@x.y"
    assert (
        SeerrUser.model_validate(
            {"id": 9, "email": "e@x.y", "plexUsername": "px"}
        ).resolved_display_name
        == "px"
    )

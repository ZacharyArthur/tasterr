import httpx
import pytest
from pydantic import SecretStr

from tasterr.auth.crypto import jellyfin_device_identifier
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.settings import Settings

USER_ID = "a" * 32
ITEM_ID = "b" * 32
KEY = "api-key-sentinel"
TOKEN = "user-token-sentinel"
USER = {"Id": USER_ID, "Name": "Viewer", "Policy": {"IsAdministrator": True, "IsDisabled": False}}
ITEM = {
    "Id": ITEM_ID,
    "ProviderIds": {"Tmdb": "550"},
    "UserData": {"LastPlayedDate": "2026-10-17T12:00:00Z"},
}


async def test_header_only_scoped_reads_auth_logout_and_shapes() -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert KEY not in str(request.url) and TOKEN not in str(request.url)
        assert request.extensions["timeout"] == {
            "connect": 5.0,
            "read": 5.0,
            "write": 5.0,
            "pool": 5.0,
        }
        if request.url.path == "/Users/AuthenticateByName":
            assert KEY not in request.headers["Authorization"]
            return httpx.Response(
                200, json={"User": USER, "AccessToken": TOKEN, "extra": "ignored"}
            )
        if request.url.path == "/Sessions/Logout":
            assert f'Token="{TOKEN}"' in request.headers["Authorization"]
            return httpx.Response(204)
        assert f'Token="{KEY}"' in request.headers["Authorization"]
        if request.url.path.startswith("/Users/"):
            return httpx.Response(200, json=USER)
        assert request.url.path == "/Items" and request.url.params["userId"] == USER_ID
        return httpx.Response(200, json={"Items": [ITEM], "TotalRecordCount": 1})

    settings = Settings(
        jellyfin_internal_url="http://jellyfin:8096", jellyfin_api_key=SecretStr(KEY)
    )
    assert settings.jellyfin_internal_url is not None
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = JellyfinClient(http, settings.jellyfin_internal_url, KEY, "stable-device")
        login = await client.authenticate("viewer", "password")
        assert login.user.id == USER_ID
        assert "extra" not in login.model_dump()
        assert TOKEN not in repr(login)
        await client.logout(login.access_token)
        assert (await client.user(USER_ID)).policy.is_administrator
        for kind in ("Movie", "Episode"):
            page = await client.played_items(USER_ID, kind, 100)
            assert page.items[0].provider_ids == {"Tmdb": "550"}
            assert requests[-1].url.params["StartIndex"] == "100"
            assert requests[-1].url.params["Filters"] == "IsPlayed"
            assert requests[-1].url.params["SortBy"] == "DatePlayed"
        assert (await client.series(USER_ID, [ITEM_ID])).total_record_count == 1
        with pytest.raises(ValueError):
            await client.series(USER_ID, [ITEM_ID] * 101)
    assert len(requests) == 6
    assert all(
        'DeviceId="stable-device"' in request.headers["Authorization"] for request in requests
    )


@pytest.mark.parametrize("status", [301, 401, 403, 404, 500, 502, 503, 504])
async def test_failure_classification_and_no_redirect(status: int) -> None:
    calls = 0

    def respond(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(status, headers={"Location": "http://elsewhere"}, text=KEY)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(respond), follow_redirects=True
    ) as http:
        client = JellyfinClient(http, "http://jellyfin", KEY, "device")
        expected = UpstreamUnavailable if status in (502, 503, 504) else UpstreamRejected
        with pytest.raises(expected) as failure:
            await client.user(USER_ID)
        assert KEY not in str(failure.value)
    assert calls == 1


@pytest.mark.parametrize("timeout", [False, True])
async def test_transport_failure(timeout: bool) -> None:
    def respond(_: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout(KEY) if timeout else httpx.ConnectError(KEY)

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(UpstreamUnavailable) as failure:
            await JellyfinClient(http, "http://jellyfin", KEY, "device").user(USER_ID)
        assert KEY not in str(failure.value)


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"Id": USER_ID, "Name": "Viewer"},
        {**USER, "Id": ITEM_ID},
        {**USER, "Policy": {"IsAdministrator": "true", "IsDisabled": False}},
    ],
)
async def test_malformed_user_is_refusal(payload: dict[str, object]) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload))
    ) as http:
        with pytest.raises(UpstreamRejected):
            await JellyfinClient(http, "http://jellyfin", KEY, "device").user(USER_ID)


def test_device_identifier_is_stable_and_secret_independent() -> None:
    assert jellyfin_device_identifier("secret") == jellyfin_device_identifier("secret")
    assert jellyfin_device_identifier("secret") != jellyfin_device_identifier("different")
    assert "secret" not in jellyfin_device_identifier("secret")

import json
import ssl
from typing import cast

import httpx
import pytest
from pydantic import ValidationError

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.http import create_http_client
from tasterr.clients.trakt import TraktClient
from tasterr.main import create_app
from tasterr.settings import PublicConfig, Settings

TOKENS = {
    "access_token": "access-fixture",
    "refresh_token": "refresh-fixture",
    "created_at": 1700000000,
    "expires_in": 604800,
}


def test_trakt_cannot_be_an_environment_sign_in_method() -> None:
    with pytest.raises(ValidationError):
        Settings.model_validate({"tasterr_sign_in_methods": ["trakt"]})


async def test_tls_verification_and_operation_surface() -> None:
    async with create_http_client() as http:
        transport = cast("httpx.AsyncHTTPTransport", http._transport)  # pyright: ignore[reportPrivateUsage]
        context = cast("ssl.SSLContext", transport._pool._ssl_context)  # pyright: ignore[reportPrivateUsage]
        assert context.verify_mode == ssl.CERT_REQUIRED and context.check_hostname
    assert {
        name
        for name, value in vars(TraktClient).items()
        if callable(value) and not name.startswith("_")
    } == {
        "device_code",
        "device_token",
        "refresh",
        "revoke",
        "user_settings",
        "last_activities",
        "history",
    }


@pytest.mark.parametrize(
    "client_id,secret,key,configured",
    [
        (None, None, None, False),
        (None, "secret", "key", False),
        ("id", None, None, False),
        ("id", None, "key", True),
        ("id", "secret", "key", True),
    ],
)
def test_configuration_and_private_projection(
    client_id: str | None,
    secret: str | None,
    key: str | None,
    configured: bool,
) -> None:
    settings = Settings.model_validate(
        {
            "trakt_client_id": client_id,
            "trakt_client_secret": secret,
            "tasterr_secret_key": key,
        }
    )
    assert settings.trakt_configured is configured
    create_app(settings)
    assert "trakt" not in PublicConfig.from_settings(settings).model_dump_json()
    assert "trakt" not in PublicConfig.model_fields
    assert "access-fixture" not in repr(settings)


@pytest.mark.parametrize("secret", [None, "secret-fixture"])
async def test_operations_hosts_headers_credentials_and_parsing(secret: str | None) -> None:
    requests: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["trakt-api-key"] == "client-fixture"
        assert request.headers["trakt-api-version"] == "2"
        assert request.headers["content-type"] == "application/json"
        assert request.headers["user-agent"].startswith("Tasterr/")
        assert request.extensions["timeout"] == dict.fromkeys(
            ("connect", "read", "write", "pool"), 10.0
        )
        assert all(
            value not in str(request.url)
            for value in (
                "client-fixture",
                "secret-fixture",
                "device-fixture",
                "access-fixture",
                "refresh-fixture",
            )
        )
        if request.url.path.startswith("/oauth/"):
            assert request.url.host == "auth.trakt.tv"
            body = json.loads(request.content)
            assert body["client_id"] == "client-fixture"
            assert "authorization" not in request.headers
            if request.url.path == "/oauth/device/code":
                assert body == {"client_id": "client-fixture"}
                return httpx.Response(
                    200,
                    json={
                        "device_code": "device-fixture",
                        "user_code": "ABCD",
                        "expires_in": 600,
                        "interval": 5,
                        "verification_url": "https://untrusted.invalid",
                    },
                )
            if request.url.path == "/oauth/device/token":
                assert body == {"client_id": "client-fixture", "code": "device-fixture"}
            if request.url.path in ("/oauth/token", "/oauth/revoke"):
                assert body.get("client_secret") == secret
                assert ("client_secret" in body) == (secret is not None)
            if request.url.path == "/oauth/token":
                expected = {
                    "client_id": "client-fixture",
                    "refresh_token": "refresh-fixture",
                    "grant_type": "refresh_token",
                    "redirect_uri": "http://localhost",
                }
                if secret:
                    expected["client_secret"] = secret
                assert body == expected
            if request.url.path == "/oauth/revoke":
                assert body["token"] == "access-fixture"
                return httpx.Response(200)
            return httpx.Response(200, json={**TOKENS, "unknown": "dropped"})
        assert request.url.host == "api.trakt.tv"
        assert request.headers["authorization"] == "Bearer access-fixture"
        if request.url.path == "/users/settings":
            return httpx.Response(
                200,
                json={
                    "user": {"username": "fixture", "ids": {"uuid": "stable", "slug": "ignored"}}
                },
            )
        if request.url.path == "/sync/last_activities":
            return httpx.Response(200, json={"movies": {"watched_at": "2026-01-01T00:00:00Z"}})
        assert dict(request.url.params) == {"limit": "250", "page": "2", "start_at": "2026-01-01"}
        return httpx.Response(
            200,
            json=[
                {
                    "watched_at": "2026-01-01T00:00:00Z",
                    "movie": {"ids": {"tmdb": 1}},
                    "unknown": True,
                }
            ],
            headers={"X-Pagination-Page-Count": "3", "X-Pagination-Limit": "100"},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        client = TraktClient(http, "client-fixture", secret)
        assert "verification_url" not in (await client.device_code()).model_dump()
        assert (await client.device_token("device-fixture")) is not None
        assert (await client.refresh("refresh-fixture")).model_dump() == TOKENS
        await client.revoke("access-fixture")
        user = (await client.user_settings("access-fixture")).user
        assert user.ids.model_dump() == {"uuid": "stable"}
        assert (await client.last_activities("access-fixture")).episodes.watched_at is None
        for kind in ("movies", "episodes"):
            page = await client.history("access-fixture", kind, page=2, start_at="2026-01-01")
            assert (page.page_count, page.page_limit) == (3, 100)
            assert "unknown" not in page.items[0].model_dump()
    assert len(requests) == 8


@pytest.mark.parametrize(
    "status,expected",
    [
        (400, "pending"),
        (404, "expired"),
        (409, "expired"),
        (410, "expired"),
        (418, "denied"),
        (420, "denied"),
        (429, "slow_down"),
    ],
)
async def test_device_statuses_with_empty_body(status: int, expected: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(status))
    ) as http:
        assert await TraktClient(http, "fixture").device_token("fixture") == expected


@pytest.mark.parametrize("status", [400, 401, 403, 302, 429, 500, 503])
async def test_generic_failures_and_no_redirects(status: int) -> None:
    seen: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return httpx.Response(
            status,
            json={"error": "invalid_grant", "secret": "DO-NOT-LEAK"},
            headers={"Location": "https://untrusted.invalid"},
        )

    expected = UpstreamUnavailable if status == 429 or status >= 500 else UpstreamRejected
    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(expected) as error:
            await TraktClient(http, "fixture").refresh("DO-NOT-LEAK")
    assert "DO-NOT-LEAK" not in str(error.value)
    assert len(seen) == 1


@pytest.mark.parametrize("body", [b"{}", b"broken", b"x" * (8 * 1024 * 1024 + 1)])
async def test_bad_bodies(body: bytes) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, content=body))
    ) as http:
        with pytest.raises(UpstreamUnavailable):
            await TraktClient(http, "fixture").device_code()


async def test_timeout_and_missing_headers() -> None:
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("DO-NOT-LEAK", request=request)

    async with httpx.AsyncClient(transport=httpx.MockTransport(timeout)) as http:
        with pytest.raises(UpstreamUnavailable, match="trakt request failed"):
            await TraktClient(http, "fixture").device_token("fixture")
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=[]))
    ) as http:
        page = await TraktClient(http, "fixture").history("fixture", "movies")
        assert page.page_count is page.page_limit is None

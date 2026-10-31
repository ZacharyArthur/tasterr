# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
# pyright: reportPrivateUsage=false
import time
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import LOCAL, db_call, link_plex, login
from tests.test_admin_api import SECRET, _app, _client
from tests.test_auth_api import PLEX_TOKEN, _harness, _poll_pin, _start_pin_login
from tests.test_clients_jellyfin import KEY, USER, USER_ID
from tests.test_clients_plex import _identity, _resource
from tests.test_jellyfin_auth import BODY, jellyfin_harness

from tasterr.api.auth import SEERR_LOGIN_SUPPORT_KEY
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.login import get_link
from tasterr.cache import Cache
from tasterr.catalog.availability import AVAIL_OPTS
from tasterr.clients.plex import PlexMediaClient
from tasterr.db.models import LinkedAccount, User
from tasterr.settings import Settings, get_settings


def test_cached_support_shared_stale_bounded_and_refreshed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    now = time.monotonic
    elapsed = 0
    monkeypatch.setattr("tasterr.cache.time.monotonic", lambda: now() + elapsed)
    reads = 0
    down = False
    server = 1

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal reads
        if request.url.path == "/api/v1/status":
            return httpx.Response(200, json={"version": "3.5.0"})
        assert request.url.path == "/api/v1/settings/public"
        reads += 1
        return (
            httpx.Response(503)
            if down
            else httpx.Response(
                200, json={"mediaServerType": server, "mediaServerLogin": True, "localLogin": True}
            )
        )

    with _client(app, tmp_path / "tasterr.db") as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        for _ in range(2):
            summary = client.get("/api/v1/integrations")
            assert summary.status_code == 200
            assert summary.json() == {
                "seerr": {
                    "configured": True,
                    "media_server": "plex",
                    "plex": True,
                    "jellyfin": False,
                    "local": True,
                },
                "plex_server_pinned": False,
                "jellyfin_configured": False,
            }
            assert client.get("/api/v1/account").json()["seerr_accepts"] == {
                "plex": True,
                "jellyfin": False,
                "local": True,
            }
        assert reads == 1
        availability_cache = cast("Cache", app.state.seerr_cache)

        async def churn_availability() -> None:
            async def absent() -> None:
                return None

            for tmdb_id in range(1, 1025):
                await availability_cache.cached(f"seerr:avail:movie:{tmdb_id}", AVAIL_OPTS, absent)
            assert len(availability_cache._values) == 1024

        assert client.portal is not None
        client.portal.call(churn_availability)
        assert client.get("/api/v1/integrations").json()["seerr"]["media_server"] == "plex"
        assert reads == 1
        elapsed = 301
        down = True
        assert client.get("/api/v1/integrations").json()["seerr"]["media_server"] == "plex"
        elapsed = 3901
        assert client.get("/api/v1/integrations").json()["seerr"] == {
            "configured": True,
            "media_server": "unknown",
            "plex": None,
            "jellyfin": None,
            "local": None,
        }
        down = False
        server = 2
        assert client.get("/api/v1/account").json()["seerr_accepts"] == {
            "plex": False,
            "jellyfin": True,
            "local": True,
        }
        server = 1
        assert client.post("/api/v1/connection-test", json={"target": "seerr"}).json()["ok"]
        assert client.get("/api/v1/integrations").json()["seerr"]["media_server"] == "plex"
        assert reads == 5


@pytest.mark.parametrize("configured", [False, True])
def test_unreadable_or_unconfigured_settings_are_unknown(tmp_path: Path, configured: bool) -> None:
    app = _app(tmp_path)
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(503)

    with _client(app, tmp_path / "tasterr.db") as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        if not configured:
            settings = cast(Settings, app.dependency_overrides[get_settings]())
            settings.seerr_api_key = None
        summary = client.get("/api/v1/integrations")
        assert summary.status_code == 200
        assert summary.json()["seerr"] == {
            "configured": configured,
            "media_server": "unknown",
            "plex": None,
            "jellyfin": None,
            "local": None,
        }
        body = client.get("/api/v1/account").json()
        assert body["seerr_accepts"] == {"plex": True, "jellyfin": True, "local": True}
        assert set(body) == {"providers", "taste_sources", "seerr_accepts"}
    assert bool(calls) is configured


def test_integration_summary_default_deny_before_http(tmp_path: Path) -> None:
    app = _app(tmp_path)

    def forbidden(_: httpx.Request) -> httpx.Response:
        pytest.fail("unauthorized upstream call")

    with TestClient(app) as client:
        assert client.get("/api/v1/integrations").status_code == 401
    with _client(app, tmp_path / "tasterr.db", is_admin=False) as client:
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(forbidden))
        assert client.get("/api/v1/integrations").status_code == 403


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("known", [False, True])
def test_plex_auto_link_known_refusal_and_unknown(
    tmp_path: Path, pinned: bool, known: bool
) -> None:
    harness = _harness(tmp_path, server_id="pinned" if pinned else None)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        harness.app.state.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(
                    200, json={"mediaServerType": 2, "mediaServerLogin": True} if known else {}
                )
            )
        )
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == (401 if known and not pinned else 200)
        assert harness.seerr.login_calls == (0 if known else 1)
        if response.status_code == 200:
            providers = client.get("/api/v1/account").json()["providers"]
            assert (
                next(row for row in providers if row["provider"] == "seerr")["linked"] is not known
            )


@pytest.mark.parametrize("known", [False, True])
def test_jellyfin_sign_in_skips_known_refusal_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, known: bool
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr:5055", seerr_api_key="key"
    )
    original = harness.upstream.respond

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/settings/public":
            return httpx.Response(
                200, json={"mediaServerType": 1, "mediaServerLogin": True} if known else {}
            )
        return original(request)

    monkeypatch.setattr(harness.upstream, "respond", respond)
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200
        assert not next(
            row
            for row in client.get("/api/v1/account").json()["providers"]
            if row["provider"] == "seerr"
        )["linked"]
    calls = [r for r in harness.upstream.requests if r.url.path == "/api/v1/auth/jellyfin"]
    assert len(calls) == (0 if known else 1)


def test_link_pin_known_refusal_stores_nothing(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        calls = harness.seerr.login_calls
        harness.app.state.http = httpx.AsyncClient(
            transport=httpx.MockTransport(
                lambda _: httpx.Response(200, json={"mediaServerType": 2, "mediaServerLogin": True})
            )
        )
        assert link_plex(client).status_code == 403
        assert harness.seerr.login_calls == calls

    async def verify(db: AsyncSession) -> None:
        assert await get_link(db, 1, "plex") is None

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("method", ["local", "plex", "jellyfin"])
def test_manual_known_refusal_precedes_decrypt_and_forward(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr:5055", seerr_api_key="key"
    )
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200

        async def add_bad_token(db: AsyncSession) -> None:
            db.add(
                LinkedAccount(
                    user_id=1,
                    provider="plex",
                    external_id="8",
                    display_name="Plex",
                    credential_enc="invalid-encryption",
                )
            )

        db_call(harness.db_path, add_bad_token)

        def respond(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/v1/settings/public"
            return httpx.Response(
                200, json={"mediaServerType": 3, "mediaServerLogin": False, "localLogin": False}
            )

        harness.app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        assert client.portal is not None
        client.portal.call(
            harness.app.state.seerr_settings_cache.invalidate, SEERR_LOGIN_SUPPORT_KEY
        )
        response = client.post("/api/v1/account/links/seerr", json={**LOCAL, "method": method})
        assert response.status_code == 409
        assert response.json() == {"detail": "Seerr does not accept this sign-in method"}

        async def verify(db: AsyncSession) -> None:
            assert await get_link(db, 1, "seerr") is None

        db_call(harness.db_path, verify)
        settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
        settings.jellyfin_api_key = None
        if method == "jellyfin":
            assert (
                client.post("/api/v1/account/links/seerr", json={"method": method}).status_code
                == 503
            )
        settings.seerr_api_key = None
        assert (
            client.post("/api/v1/account/links/seerr", json={"method": method}).status_code == 503
        )


@pytest.mark.parametrize("target", ["plex", "jellyfin"])
@pytest.mark.parametrize("configured", [False, True])
def test_connection_without_link(tmp_path: Path, target: str, configured: bool) -> None:
    app = _app(tmp_path)
    calls: list[str] = []

    def respond(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        assert target == "jellyfin" and request.url.path == "/System/Info/Public"
        assert "Token=" not in request.headers["Authorization"]
        return httpx.Response(200, json={"Version": "10.10.0", "ServerName": "private"})

    with _client(app, tmp_path / "tasterr.db") as client:
        settings = cast(Settings, app.dependency_overrides[get_settings]())
        if not configured:
            settings.seerr_api_key = None
        if target == "jellyfin" and configured:
            settings.jellyfin_internal_url = "http://jellyfin:8096"
            settings.jellyfin_api_key = SecretStr(KEY)
        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        response = client.post("/api/v1/connection-test", json={"target": target})
        detail = (
            f"{target.capitalize()} is not configured"
            if not configured
            else "Link Plex on your Account page to test it"
            if target == "plex"
            else "Jellyfin is reachable. Link your Jellyfin account to verify the API key"
        )
        assert response.json() == {"target": target, "ok": False, "detail": detail}
    assert calls == (["/System/Info/Public"] if configured and target == "jellyfin" else [])


@pytest.mark.parametrize("linked", [False, True])
@pytest.mark.parametrize("status", [200, 401, 503])
def test_jellyfin_connection_key_scoped_or_public(
    tmp_path: Path, linked: bool, status: int
) -> None:
    app = _app(tmp_path)
    with _client(app, tmp_path / "tasterr.db") as client:
        settings = cast(Settings, app.dependency_overrides[get_settings]())
        settings.jellyfin_internal_url = "http://jellyfin:8096"
        settings.jellyfin_api_key = SecretStr(KEY)
        if linked:

            async def add_link(db: AsyncSession) -> None:
                db.add(
                    LinkedAccount(
                        user_id=1,
                        provider="jellyfin",
                        external_id=USER_ID,
                        display_name="private-name",
                    )
                )

            db_call(tmp_path / "tasterr.db", add_link)
        calls: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            assert request.url.path == (f"/Users/{USER_ID}" if linked else "/System/Info/Public")
            assert (f'Token="{KEY}"' in request.headers["Authorization"]) is linked
            return httpx.Response(status, json=USER if linked else {"Version": "10.10.0"})

        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        response = client.post("/api/v1/connection-test", json={"target": "jellyfin"})
        assert response.json() == {
            "target": "jellyfin",
            "ok": linked and status == 200,
            "detail": "Connection failed"
            if status != 200
            else "Connection successful"
            if linked
            else "Jellyfin is reachable. Link your Jellyfin account to verify the API key",
        }
        assert len(calls) == 1


@pytest.mark.parametrize("outcome", ["success", "empty", "refused", "outage", "deadline"])
def test_plex_connection_uses_own_link_and_pinned_discovery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, outcome: str
) -> None:
    app = _app(tmp_path)
    with _client(app, tmp_path / "tasterr.db") as client:
        settings = cast(Settings, app.dependency_overrides[get_settings]())
        settings.plex_server_id = "pinned"

        async def add_link(db: AsyncSession) -> None:
            db.add(
                LinkedAccount(
                    user_id=1,
                    provider="plex",
                    external_id="8",
                    display_name="private-name",
                    credential_enc=encrypt_token(SECRET, PLEX_TOKEN),
                )
            )
            db.add(
                LinkedAccount(
                    user_id=2,
                    provider="plex",
                    external_id="9",
                    display_name="other",
                    credential_enc="must-not-decrypt",
                )
            )

        # A second user's credential must never be selected.
        async def seed(db: AsyncSession) -> None:
            db.add(User(id=2, display_name="Other"))
            await db.flush()
            await add_link(db)

        db_call(tmp_path / "tasterr.db", seed)
        calls: list[str] = []

        def respond(request: httpx.Request) -> httpx.Response:
            calls.append(request.url.path)
            if request.url.path == "/identity":
                assert "X-Plex-Token" not in request.headers
                return _identity("pinned")
            assert request.headers["X-Plex-Token"] == PLEX_TOKEN
            if outcome in ("refused", "outage"):
                return httpx.Response(
                    401 if outcome == "refused" else 503,
                    json={"private-name": "http://private-server"},
                )
            if request.url.path == "/api/v2/user":
                return httpx.Response(200, json={"id": 8, "username": "private-name"})
            assert request.url.path == "/api/v2/resources"
            return httpx.Response(
                200,
                json=[]
                if outcome == "empty"
                else [
                    _resource("pinned", "https://pinned.plex.direct:32400"),
                    _resource("other", "https://other.plex.direct:32400"),
                ],
            )

        app.state.http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
        if outcome == "deadline":

            async def expired(_self: PlexMediaClient, _token: str) -> None:
                raise TimeoutError

            monkeypatch.setattr(PlexMediaClient, "account", expired)
        response = client.post("/api/v1/connection-test", json={"target": "plex"})
        assert response.json() == {
            "target": "plex",
            "ok": outcome == "success",
            "detail": "Connection successful"
            if outcome == "success"
            else "Plex.tv works, but no Plex server was reachable"
            if outcome == "empty"
            else "Connection failed",
        }
        if outcome == "success":
            assert calls == ["/api/v2/user", "/api/v2/resources", "/identity"]

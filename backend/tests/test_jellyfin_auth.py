# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import db_call
from tests.test_clients_jellyfin import KEY, TOKEN, USER, USER_ID

from tasterr.auth.ratelimit import TokenBucket
from tasterr.db.models import LinkedAccount, User
from tasterr.main import create_app
from tasterr.settings import Settings

BODY = {"username": "Viewer", "password": "password-sentinel"}


class JellyfinUpstream:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.auth_status = 200
        self.logout_status = 204
        self.user_status = 200
        self.seerr_status = 403
        self.admin = False
        self.disabled = False

    def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        user = {**USER, "Policy": {"IsAdministrator": self.admin, "IsDisabled": self.disabled}}
        if request.url.path == "/Users/AuthenticateByName":
            return httpx.Response(self.auth_status, json={"User": user, "AccessToken": TOKEN})
        if request.url.path == "/Sessions/Logout":
            return httpx.Response(self.logout_status)
        if request.url.path.startswith("/Users/"):
            return httpx.Response(self.user_status, json=user)
        if request.url.path == "/Items":
            return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})
        if request.url.path.startswith("/api/v1/"):
            status = self.seerr_status if request.url.path.startswith("/api/v1/auth/") else 200
            return httpx.Response(
                status,
                json={"id": 7, "displayName": "Seerr Viewer", "permissions": 0},
                headers={"Set-Cookie": "connect.sid=seerr-cookie; Path=/"},
            )
        raise AssertionError("unexpected upstream path")


@dataclass
class JellyfinHarness:
    app: FastAPI
    db_path: Path
    upstream: JellyfinUpstream


def jellyfin_harness(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **overrides: object
) -> JellyfinHarness:
    upstream = JellyfinUpstream()
    monkeypatch.setattr(
        "tasterr.main.create_http_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(upstream.respond)),
    )
    settings = Settings.model_validate(
        {
            "database_path": tmp_path / "test.db",
            "static_dir": tmp_path / "static",
            "tasterr_secret_key": "test-secret-key",
            "jellyfin_internal_url": "http://jellyfin:8096",
            "jellyfin_api_key": KEY,
            **overrides,
        }
    )
    return JellyfinHarness(create_app(settings), settings.database_path, upstream)


@pytest.mark.parametrize("logout_status", [204, 401, 503])
def test_success_stores_only_id_and_failed_logout_still_signs_in(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, logout_status: int
) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch)
    harness.upstream.logout_status = logout_status
    with TestClient(harness.app) as client:
        response = client.post("/api/v1/auth/jellyfin", json=BODY)
        assert response.status_code == 200
        assert response.json() == {
            "id": 1,
            "display_name": "Viewer",
            "avatar_url": None,
            "is_admin": False,
        }
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.get("/api/v1/auth/methods").json() == {
            "plex": False,
            "jellyfin": True,
            "seerr": False,
        }
        assert KEY not in response.text and TOKEN not in response.text
    assert [request.url.path for request in harness.upstream.requests[:2]] == [
        "/Users/AuthenticateByName",
        "/Sessions/Logout",
    ]

    async def verify(db: AsyncSession) -> None:
        link = (await db.scalars(select(LinkedAccount))).one()
        assert link.provider == "jellyfin" and link.external_id == USER_ID
        assert link.credential_enc is link.avatar_url is None

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("status,expected", [(401, 401), (403, 401), (500, 401), (503, 502)])
def test_rejection_is_generic_and_creates_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, expected: int
) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch)
    harness.upstream.auth_status = status
    with TestClient(harness.app) as client:
        response = client.post("/api/v1/auth/jellyfin", json=BODY)
        assert response.status_code == expected
        assert response.json()["detail"] == (
            "Sign-in failed" if expected == 401 else "Sign-in service unavailable"
        )
        assert "set-cookie" not in response.headers

    async def verify(db: AsyncSession) -> None:
        assert (await db.scalars(select(User))).all() == []

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("allowed", [False, True])
def test_empty_password_checked_before_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, allowed: bool
) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch, jellyfin_allow_empty_password=allowed)
    with TestClient(harness.app) as client:
        response = client.post("/api/v1/auth/jellyfin", json={**BODY, "password": ""})
        assert response.status_code == (200 if allowed else 401)
    assert bool(harness.upstream.requests) is allowed


@pytest.mark.parametrize(
    "overrides",
    [{"jellyfin_internal_url": None}, {"jellyfin_api_key": None}, {"tasterr_secret_key": None}],
)
def test_unconfigured_is_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, overrides: dict[str, object]
) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch, **overrides)
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 503
    assert harness.upstream.requests == []


def test_login_guards_precede_upstream(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch)
    with TestClient(harness.app) as client:
        assert (
            client.post(
                "/api/v1/auth/jellyfin", json=BODY, headers={"Sec-Fetch-Site": "cross-site"}
            ).status_code
            == 403
        )
        harness.app.state.login_bucket = TokenBucket(capacity=0, refill_per_second=0)
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 429
    assert harness.upstream.requests == []


@pytest.mark.parametrize("status", [200, 403, 500, 503])
@pytest.mark.parametrize("existing", [False, True])
def test_seerr_auto_link_and_outage_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, existing: bool
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr:5055", seerr_api_key="seerr-key"
    )
    with TestClient(harness.app) as client:
        if existing:
            assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200
        harness.upstream.seerr_status = status
        response = client.post("/api/v1/auth/jellyfin", json=BODY)
        assert response.status_code == (502 if status == 503 and not existing else 200)
        if status == 200:
            assert response.json()["display_name"] == "Seerr Viewer"
    calls = [
        request
        for request in harness.upstream.requests
        if request.url.path == "/api/v1/auth/jellyfin"
    ]
    assert len(calls) == (2 if existing else 1)
    assert calls[-1].content == b'{"username":"Viewer","password":"password-sentinel"}'

    async def verify(db: AsyncSession) -> None:
        links = (await db.scalars(select(LinkedAccount))).all()
        assert {link.provider for link in links} == (
            {"jellyfin", "seerr"}
            if status == 200
            else {"jellyfin"}
            if existing or status != 503
            else set()
        )

    db_call(harness.db_path, verify)


@pytest.mark.parametrize(
    "status,disabled,expected",
    [
        (200, False, True),
        (200, True, False),
        (404, False, False),
        (401, False, False),
        (500, False, False),
        (503, False, True),
    ],
)
def test_admin_any_link_outage_refusal_and_disabled_user(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: int, disabled: bool, expected: bool
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr:5055", seerr_api_key="key"
    )
    harness.upstream.admin = True
    harness.upstream.seerr_status = 200
    with TestClient(harness.app) as client:
        first = client.post("/api/v1/auth/jellyfin", json=BODY)
        assert first.status_code == 200 and first.json()["is_admin"]
        assert first.json()["display_name"] == "Seerr Viewer"
        harness.upstream.user_status = status
        harness.upstream.disabled = disabled
        response = client.post(
            "/api/v1/auth/local", json={"email": "viewer@example.test", "password": "password"}
        )
        assert response.status_code == 200 and response.json()["is_admin"] is expected


def test_display_plex_precedes_jellyfin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch)
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200

        async def add_plex(db: AsyncSession) -> None:
            db.add(
                LinkedAccount(
                    user_id=1,
                    provider="plex",
                    external_id="plex-id",
                    display_name="Plex Name",
                    avatar_url="https://example.test/avatar",
                )
            )

        db_call(harness.db_path, add_plex)
        response = client.post("/api/v1/auth/jellyfin", json=BODY)
        assert response.json()["display_name"] == "Plex Name"

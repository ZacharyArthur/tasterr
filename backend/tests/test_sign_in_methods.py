# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.sql import Executable
from tests.test_account_api import LOCAL, db_call, link_plex, login
from tests.test_admin_api import _app, _client
from tests.test_auth_api import PLEX_TOKEN, _harness
from tests.test_browse_api import FakeCatalog
from tests.test_clients_jellyfin import TOKEN, USER

from tasterr.api import admin
from tasterr.api.auth import AuthContext, get_auth_context
from tasterr.api.catalog import get_catalog
from tasterr.catalog.models import HomeFeed
from tasterr.catalog.service import CatalogService
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.db.models import LinkedAccount, User
from tasterr.db.runtime_settings import save_runtime_settings
from tasterr.main import create_app
from tasterr.rails.registry import RailContext
from tasterr.runtime_settings import RuntimeSettings
from tasterr.settings import Settings, get_settings


def test_runtime_defaults_validation_and_round_trip() -> None:
    assert RuntimeSettings.model_validate({"region": "GB"}).disabled_sign_in_methods == []
    runtime = RuntimeSettings(disabled_sign_in_methods=["plex", "seerr"])
    assert RuntimeSettings.model_validate_json(runtime.model_dump_json()) == runtime
    for value in (["plex", "plex"], ["trakt"], None, "plex"):
        with pytest.raises(ValidationError):
            RuntimeSettings.model_validate({"disabled_sign_in_methods": value})


@pytest.mark.parametrize(
    "value",
    [
        '["plex"]',
        '["jellyfin"]',
        '["seerr"]',
        '["plex","jellyfin"]',
        '["plex","seerr"]',
        '["jellyfin","seerr"]',
        '["plex","jellyfin","seerr"]',
    ],
)
def test_environment_allowlist_and_lock(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.delenv("TASTERR_SIGN_IN_METHODS", raising=False)
    stored = RuntimeSettings(disabled_sign_in_methods=["plex"])
    assert Settings().resolve_runtime(stored) == stored
    monkeypatch.setenv("TASTERR_SIGN_IN_METHODS", value)
    settings = Settings()
    effective = settings.resolve_runtime(stored)
    assert "disabled_sign_in_methods" in settings.locked_discovery_fields
    assert effective.disabled_sign_in_methods == [
        method for method in ("plex", "jellyfin", "seerr") if method not in value
    ]
    assert stored.disabled_sign_in_methods == ["plex"]


@pytest.mark.parametrize(
    "value", ["[]", "null", "", '["trakt"]', '["plex","plex"]', '"plex"', "[true]"]
)
def test_invalid_environment_fails_boot(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv("TASTERR_SIGN_IN_METHODS", value)
    with pytest.raises(ValidationError):
        Settings()


@pytest.mark.parametrize("locked", [False, True])
def test_hidden_sign_in_endpoints_are_generic_and_upstream_free(
    tmp_path: Path, locked: bool
) -> None:
    settings = Settings(
        database_path=tmp_path / "tasterr.db",
        static_dir=tmp_path / "static",
        tasterr_secret_key=SecretStr("test-secret-key"),
        plex_server_id="pinned",
        seerr_internal_url="http://seerr",
        seerr_api_key=SecretStr("key"),
        jellyfin_internal_url="http://jellyfin",
        jellyfin_api_key=SecretStr("key"),
    )
    app = create_app(settings)
    calls: list[str] = []
    with TestClient(app) as client:
        if locked:
            settings.tasterr_sign_in_methods = ["jellyfin"]
        else:

            async def store(db: AsyncSession) -> None:
                await save_runtime_settings(
                    db, RuntimeSettings(disabled_sign_in_methods=["plex", "seerr"])
                )

            db_call(settings.database_path, store)

        async def record(request: httpx.Request) -> None:
            calls.append(request.url.path)
            raise AssertionError("Hidden sign-in must not call upstream")

        app.state.http.event_hooks["request"].append(record)
        assert client.get("/api/v1/auth/methods").json() == {
            "plex": False,
            "jellyfin": True,
            "seerr": False,
        }
        for route, body in (
            ("plex/pin", {}),
            ("plex/pin/poll", {"pin_id": "unknown"}),
            ("local", LOCAL),
        ):
            response = client.post(f"/api/v1/auth/{route}", json=body)
            assert response.status_code == 503
            assert response.json() == {"detail": "Authentication unavailable"}
        settings.tasterr_sign_in_methods = ["plex"]
        response = client.post(
            "/api/v1/auth/jellyfin", json={"username": "member", "password": "password"}
        )
        assert response.status_code == 503
        assert response.json() == {"detail": "Authentication unavailable"}
    assert calls == []


def test_hidden_providers_can_link_and_last_offered_cannot_unlink(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    harness.plex.token = PLEX_TOKEN
    settings.jellyfin_internal_url = "http://jellyfin"
    settings.jellyfin_api_key = SecretStr("key")

    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Users/AuthenticateByName":
            return httpx.Response(200, json={"User": USER, "AccessToken": TOKEN})
        assert request.url.path == "/Sessions/Logout"
        return httpx.Response(204)

    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ctx = cast(AuthContext, harness.app.dependency_overrides[get_auth_context]())
    ctx.jellyfin = JellyfinClient(http, "http://jellyfin", "key", "device")
    harness.app.dependency_overrides[get_auth_context] = lambda: ctx
    with TestClient(harness.app) as client:
        login(client)
        settings.tasterr_sign_in_methods = ["seerr"]
        assert link_plex(client).status_code == 200
        assert (
            client.post(
                "/api/v1/account/links/jellyfin",
                json={"username": "member", "password": "password"},
            ).status_code
            == 204
        )
        rows = client.get("/api/v1/account").json()["providers"]
        assert [(row["provider"], row["available"], row["sign_in"]) for row in rows] == [
            ("plex", True, False),
            ("jellyfin", True, False),
            ("seerr", True, True),
        ]
        assert rows[2]["can_unlink"] is False
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 409
        settings.tasterr_sign_in_methods = ["jellyfin"]
        assert client.post("/api/v1/account/links/seerr", json=LOCAL).status_code == 204
        assert client.post("/api/v1/account/links/jellyfin/unlink", json={}).status_code == 409
        assert client.post("/api/v1/account/links/plex/unlink", json={}).status_code == 204


def test_admin_counts_save_guard_and_locked_preservation(tmp_path: Path) -> None:
    app = _app(tmp_path)
    settings = cast(Settings, app.dependency_overrides[get_settings]())
    settings.jellyfin_internal_url = "http://jellyfin"
    settings.jellyfin_api_key = SecretStr("key")
    with _client(app, settings.database_path) as client:

        async def seed(db: AsyncSession) -> None:
            for index, methods in enumerate(
                (("plex",), ("plex",), ("plex", "seerr"), ("jellyfin",), ())
            ):
                user = User(display_name=f"Private member {index}")
                db.add(user)
                await db.flush()
                for method in methods:
                    db.add(
                        LinkedAccount(
                            user_id=user.id,
                            provider=method,
                            external_id=f"fixture-{index}",
                            display_name="Private link",
                        )
                    )

        db_call(settings.database_path, seed)
        body = client.get("/api/v1/settings").json()
        assert body["configured_sign_in_methods"] == ["plex", "jellyfin", "seerr"]
        assert body["sign_in_link_counts"] == [
            {"methods": [], "count": 1},
            {"methods": ["jellyfin"], "count": 1},
            {"methods": ["plex"], "count": 2},
            {"methods": ["plex", "seerr"], "count": 1},
            {"methods": ["seerr"], "count": 1},
        ]
        assert "Private member" not in str(body)
        before = body["settings"]
        denied = client.put(
            "/api/v1/settings", json={"region": "GB", "disabled_sign_in_methods": ["plex", "seerr"]}
        )
        assert denied.status_code == 409
        assert client.get("/api/v1/settings").json()["settings"] == before
        saved = client.put(
            "/api/v1/settings", json={"disabled_sign_in_methods": ["plex", "jellyfin"]}
        )
        assert saved.status_code == 200
        assert client.get("/api/v1/auth/methods").json() == {
            "plex": False,
            "jellyfin": False,
            "seerr": True,
        }
        settings.tasterr_sign_in_methods = ["plex", "seerr"]
        locked = client.put(
            "/api/v1/settings", json={"region": "GB", "disabled_sign_in_methods": ["seerr"]}
        )
        assert locked.status_code == 200
        assert "disabled_sign_in_methods" in locked.json()["locked_fields"]
        assert locked.json()["settings"]["disabled_sign_in_methods"] == ["jellyfin"]
        settings.tasterr_sign_in_methods = None
        restored = client.get("/api/v1/settings").json()["settings"]
        assert restored["disabled_sign_in_methods"] == ["plex", "jellyfin"]
        assert restored["region"] == "GB"
        settings.jellyfin_internal_url = None
        counts = client.get("/api/v1/settings").json()["sign_in_link_counts"]
        assert counts[0] == {"methods": [], "count": 2}
        assert all("jellyfin" not in row["methods"] for row in counts)


def test_hidden_plex_still_schedules_history_and_continue_watching(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    harness.plex.token = PLEX_TOKEN
    harness.app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, FakeCatalog())
    history_users: list[int] = []

    def schedule(_request: object, _settings: object, user_id: int, *_args: object) -> None:
        history_users.append(user_id)

    async def home(context: RailContext) -> HomeFeed:
        assert context.plex is not None
        assert context.plex_account_token is not None
        return HomeFeed(hero=[], rails=[])

    with TestClient(harness.app) as client:
        login(client)
        assert link_plex(client).status_code == 200
        settings.tasterr_sign_in_methods = ["seerr"]
        monkeypatch.setattr("tasterr.api.taste.schedule_plex_history", schedule)
        monkeypatch.setattr("tasterr.api.home.build_home", home)
        assert client.get("/api/v1/home").status_code == 200
        assert history_users == [1]


def test_unlink_uses_methods_current_after_waiting_for_history(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        assert link_plex(client).status_code == 200
        maker = cast(async_sessionmaker[AsyncSession], harness.app.state.sessionmaker)

        async def hide_plex(*_args: object) -> None:
            async with maker() as db:
                await save_runtime_settings(db, RuntimeSettings(disabled_sign_in_methods=["plex"]))
                await db.commit()

        monkeypatch.setattr("tasterr.api.account.cancel_source_history", hide_plex)
        response = client.post("/api/v1/account/links/seerr/unlink", json={})
        assert response.status_code == 409
        rows = client.get("/api/v1/account").json()["providers"]
        assert next(row for row in rows if row["provider"] == "seerr")["linked"] is True


@pytest.mark.parametrize("method", ["GET", "PUT"])
def test_settings_response_survives_concurrent_member_creation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    app = _app(tmp_path)
    build_response = admin.settings_response
    created = False
    with _client(app, tmp_path / "tasterr.db") as client:
        maker = cast(async_sessionmaker[AsyncSession], app.state.sessionmaker)

        async def interleaved_response(
            db: AsyncSession, settings: Settings, runtime: RuntimeSettings
        ) -> admin.SettingsResponse:
            original_execute = db.execute

            async def execute(statement: Executable, **_kwargs: object):
                nonlocal created
                result = await original_execute(statement)
                if not created:
                    created = True
                    async with maker() as other:
                        user = User(display_name="New member")
                        other.add(user)
                        await other.flush()
                        other.add(
                            LinkedAccount(
                                user_id=user.id,
                                provider="seerr",
                                external_id="new-member",
                                display_name="New member",
                            )
                        )
                        await other.commit()
                return result

            monkeypatch.setattr(db, "execute", execute)
            return await build_response(db, settings, runtime)

        monkeypatch.setattr(admin, "settings_response", interleaved_response)
        response = client.request(
            method, "/api/v1/settings", json={"region": "GB"} if method == "PUT" else None
        )
        assert response.status_code == 200
        assert created
        assert response.json()["sign_in_link_counts"] == [{"methods": ["seerr"], "count": 1}]
        reread = client.get("/api/v1/settings").json()
        assert reread["sign_in_link_counts"] == [{"methods": ["seerr"], "count": 2}]
        assert reread["settings"]["region"] == ("GB" if method == "PUT" else "US")

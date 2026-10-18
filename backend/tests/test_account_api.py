# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.test_auth_api import PLEX_TOKEN, SECRET, _harness, _poll_pin, _start_pin_login

from tasterr.api.taste import history_guard
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.login import CONFLICT_GUIDANCE, get_link
from tasterr.auth.ratelimit import TokenBucket
from tasterr.cache import CacheOpts
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexCloudAccount, PlexResourceAccess
from tasterr.db.engine import create_engine
from tasterr.db.models import LinkedAccount, Profile, Signal, User, UserSession
from tasterr.recommend.seed import reserve_seed
from tasterr.settings import Settings, get_settings

LOCAL = {"method": "local", "email": "a@b.c", "password": "hunter2-password-sentinel"}


def db_call[T](path: Path, action: Callable[[AsyncSession], Awaitable[T]]) -> T:
    async def run() -> T:
        engine = create_engine(path)
        try:
            async with async_sessionmaker(engine, expire_on_commit=False)() as db:
                result = await action(db)
                await db.commit()
                return result
        finally:
            await engine.dispose()

    return asyncio.run(run())


def login(client: TestClient) -> None:
    assert client.post("/api/v1/auth/local", json=LOCAL).status_code == 200


def link_plex(client: TestClient) -> httpx.Response:
    created = client.post("/api/v1/account/links/plex/pin")
    assert created.status_code == 200
    return client.post(
        "/api/v1/account/links/plex/pin/poll", json={"pin_id": created.json()["pin_id"]}
    )


def test_pinned_link_admission_and_dormant_seerr_unlink(tmp_path: Path) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    with TestClient(harness.app) as client:
        login(client)
        harness.plex.resource_list = []
        assert link_plex(client).status_code == 403

        async def no_plex(db: AsyncSession) -> None:
            assert await get_link(db, 1, "plex") is None
            assert len((await db.scalars(select(UserSession))).all()) == 1

        db_call(harness.db_path, no_plex)
        harness.plex.resource_list = [PlexResourceAccess(clientIdentifier="pinned", owned=False)]
        harness.seerr.down = True
        calls = harness.seerr.login_calls
        assert link_plex(client).status_code == 200
        assert harness.seerr.login_calls == calls
        settings.seerr_internal_url = None
        settings.seerr_api_key = None
        rows = client.get("/api/v1/account").json()["providers"]
        assert [(row["provider"], row["available"], row["can_unlink"]) for row in rows] == [
            ("plex", True, False),
            ("seerr", False, True),
        ]
        assert client.post("/api/v1/account/links/seerr", json=LOCAL).status_code == 503
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 204
        assert client.get("/api/v1/account").json()["providers"][0]["linked"]
        settings.plex_server_id = None
        assert client.post("/api/v1/account/links/plex/pin").status_code == 503
        assert (
            client.post("/api/v1/account/links/plex/pin/poll", json={"pin_id": "any"}).status_code
            == 503
        )


@pytest.mark.parametrize("outage", [False, True])
def test_pinned_link_resource_failure_stores_nothing(tmp_path: Path, outage: bool) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    harness.plex.resource_error = UpstreamUnavailable("outage") if outage else UpstreamRejected(401)
    with TestClient(harness.app) as client:
        login(client)
        response = link_plex(client)
        assert response.status_code == (502 if outage else 403)
        assert "set-cookie" not in response.headers

        async def verify(db: AsyncSession) -> None:
            assert await get_link(db, 1, "plex") is None

        db_call(harness.db_path, verify)


def test_summary_link_refresh_unlink_and_credentials_survive_logout(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        before = client.get("/api/v1/account").json()["providers"]
        assert before[1]["linked"] is True and before[1]["can_unlink"] is False
        assert link_plex(client).status_code == 200
        assert link_plex(client).status_code == 200
        body = client.get("/api/v1/account").json()
        assert all(row["can_unlink"] for row in body["providers"])
        assert set(body["providers"][0]) == {
            "provider",
            "available",
            "linked",
            "display_name",
            "linked_at",
            "can_unlink",
        }
        assert client.post("/api/v1/auth/logout").status_code == 204

        async def credential(db: AsyncSession) -> str:
            rows = (
                await db.scalars(select(LinkedAccount).where(LinkedAccount.provider == "plex"))
            ).all()
            assert len(rows) == 1
            return decrypt_token(SECRET, rows[0].credential_enc or "")

        assert db_call(harness.db_path, credential) == PLEX_TOKEN
        login(client)
        assert client.post("/api/v1/account/links/plex/unlink", json={}).status_code == 204

        async def removed(db: AsyncSession) -> None:
            assert await get_link(db, 1, "plex") is None

        db_call(harness.db_path, removed)
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 409


@pytest.mark.parametrize(
    "path,body",
    [
        ("/account/links/plex/pin", {}),
        ("/account/links/plex/pin/poll", {"pin_id": "unknown"}),
        ("/account/links/seerr", LOCAL),
        ("/account/links/plex/unlink", {}),
        ("/account/delete", {"confirm": "Viewer"}),
    ],
)
def test_mutation_guards(tmp_path: Path, path: str, body: dict[str, object]) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        assert client.post("/api/v1" + path, json=body).status_code == 401
        login(client)
        assert (
            client.post(
                "/api/v1" + path, json=body, headers={"origin": "https://other.example"}
            ).status_code
            == 403
        )
        harness.app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)
        assert client.post("/api/v1" + path, json=body).status_code == 429


def test_link_pin_binding_and_login_bucket_exemption(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        login(client)
        sign_in = _start_pin_login(client)
        linked = client.post("/api/v1/account/links/plex/pin").json()["pin_id"]
        assert _poll_pin(client, linked).status_code == 404
        assert (
            client.post("/api/v1/account/links/plex/pin/poll", json={"pin_id": sign_in}).status_code
            == 404
        )
        login(client)  # same member, a different session
        assert (
            client.post("/api/v1/account/links/plex/pin/poll", json={"pin_id": linked}).status_code
            == 404
        )
        handle = client.post("/api/v1/account/links/plex/pin").json()["pin_id"]
        harness.app.state.login_bucket = TokenBucket(capacity=0, refill_per_second=0)
        harness.plex.token = PLEX_TOKEN
        assert (
            client.post("/api/v1/account/links/plex/pin/poll", json={"pin_id": handle}).status_code
            == 200
        )
        assert client.post("/api/v1/account/links/plex/pin").status_code == 429


@pytest.mark.parametrize("outage", [False, True])
def test_plex_admission_failure_stores_nothing(tmp_path: Path, outage: bool) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        login(client)
        harness.plex.token = "refused" if not outage else PLEX_TOKEN
        harness.seerr.down = outage
        result = link_plex(client)
        assert result.status_code == (502 if outage else 403)
        providers = client.get("/api/v1/account").json()["providers"]
        assert providers[0]["linked"] is False


def test_plex_admission_discards_seerr_login_and_manual_link_clears_flag(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        assert (
            client.post("/api/v1/account/links/seerr", json={"method": "plex"}).status_code == 409
        )
        assert link_plex(client).status_code == 200
        assert client.get("/api/v1/auth/me").json()["is_admin"] is True
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 204
        assert client.get("/api/v1/auth/me").json()["is_admin"] is True
        assert link_plex(client).status_code == 200
        assert client.get("/api/v1/account").json()["providers"][1]["linked"] is False
        assert (
            client.post(
                "/api/v1/account/links/seerr", json={**LOCAL, "password": "wrong"}
            ).status_code
            == 401
        )
        assert (
            client.post("/api/v1/account/links/seerr", json={"method": "plex"}).status_code == 204
        )

    async def verify(db: AsyncSession) -> None:
        user = (await db.scalars(select(User))).one()
        assert user.seerr_unlinked_at is None
        link = await get_link(db, user.id, "seerr")
        assert link is not None and link.credential_enc is not None

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("delete_history", [False, True])
def test_unlink_history_and_continue_cache(tmp_path: Path, delete_history: bool) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN

    async def seed(db: AsyncSession) -> None:
        db.add(Signal(user_id=1, tmdb_id=42, media_type="movie", kind="watched_plex", weight=2.5))
        db.add(Profile(user_id=1, vector="{}"))

    with TestClient(harness.app) as client:
        login(client)
        assert link_plex(client).status_code == 200
        db_call(harness.db_path, seed)
        assert client.portal is not None

        async def load() -> str:
            return "cached"

        client.portal.call(
            harness.app.state.catalog_cache.cached,
            "plex:continue-watching:user:1",
            CacheOpts(300, 0),
            load,
        )
        assert (
            client.post(
                "/api/v1/account/links/plex/unlink", json={"delete_history": delete_history}
            ).status_code
            == 204
        )

        async def replacement() -> str:
            return "cleared"

        assert (
            client.portal.call(
                harness.app.state.catalog_cache.cached,
                "plex:continue-watching:user:1",
                CacheOpts(300, 0),
                replacement,
            )
            == "cleared"
        )

    async def verify(db: AsyncSession) -> None:
        assert len((await db.scalars(select(Signal))).all()) == (0 if delete_history else 1)
        assert (await db.get(Profile, 1) is None) is delete_history

    db_call(harness.db_path, verify)


def test_account_deletion_cascade_wrong_confirmation_and_session_invalidation(
    tmp_path: Path,
) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        login(client)
        assert client.post("/api/v1/account/delete", json={"confirm": "wrong"}).status_code == 422

        async def seed(db: AsyncSession) -> None:
            db.add(Signal(user_id=1, tmdb_id=42, media_type="movie", kind="request", weight=3))
            db.add(Profile(user_id=1, vector="{}"))

        db_call(harness.db_path, seed)
        assert client.portal is not None

        async def cached() -> str:
            return "cached"

        client.portal.call(
            harness.app.state.catalog_cache.cached,
            "plex:continue-watching:user:1",
            CacheOpts(300, 0),
            cached,
        )
        response = client.post("/api/v1/account/delete", json={"confirm": "Viewer"})
        assert response.status_code == 204 and "set-cookie" not in response.headers
        assert client.cookies.get("tasterr_session") is not None
        assert client.get("/api/v1/auth/me").status_code == 401

        async def replacement() -> str:
            return "cleared"

        assert (
            client.portal.call(
                harness.app.state.catalog_cache.cached,
                "plex:continue-watching:user:1",
                CacheOpts(300, 0),
                replacement,
            )
            == "cleared"
        )

    async def verify(db: AsyncSession) -> None:
        for model in (User, UserSession, LinkedAccount, Signal, Profile):
            assert (await db.scalars(select(model))).all() == []

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("_repeat", range(10))
async def test_concurrent_unlinks_keep_one_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, _repeat: int
) -> None:
    arrivals = 0
    both_entered = asyncio.Event()

    @asynccontextmanager
    async def overlapping(request: Request, user_id: int) -> AsyncGenerator[None]:
        nonlocal arrivals
        arrivals += 1
        if arrivals == 2:
            both_entered.set()
        async with history_guard(request, user_id):
            await asyncio.wait_for(both_entered.wait(), 5)
            yield

    monkeypatch.setattr("tasterr.api.account.history_guard", overlapping)
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
    ):
        await client.post("/api/v1/auth/local", json=LOCAL)
        created = await client.post("/api/v1/account/links/plex/pin")
        await client.post(
            "/api/v1/account/links/plex/pin/poll", json={"pin_id": created.json()["pin_id"]}
        )
        results = await asyncio.gather(
            *(
                client.post(f"/api/v1/account/links/{provider}/unlink", json={})
                for provider in ("plex", "seerr")
            )
        )
        assert sorted(result.status_code for result in results) == [204, 409]
        assert arrivals == 2


def test_dormant_link_and_unconfigured_remaining_link(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        assert link_plex(client).status_code == 200

        def available(_settings: object, provider: str) -> bool:
            return provider == "seerr"

        monkeypatch.setattr(
            "tasterr.api.account.provider_available",
            available,
        )
        providers = client.get("/api/v1/account").json()["providers"]
        assert providers[0]["available"] is False and providers[0]["can_unlink"] is True
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 409
        assert client.post("/api/v1/account/links/plex/unlink", json={}).status_code == 204


def test_conflict_is_generic_and_other_members_links_are_untouched(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)

        async def other(db: AsyncSession) -> None:
            user = User(display_name="private-other-member")
            db.add(user)
            await db.flush()
            db.add(
                LinkedAccount(
                    user_id=user.id, provider="plex", external_id="8", display_name="private-name"
                )
            )

        db_call(harness.db_path, other)
        response = link_plex(client)
        assert response.status_code == 409
        assert "private" not in response.text and "delete the other" in response.json()["detail"]
        assert client.get("/api/v1/account").json()["providers"][0]["linked"] is False


def test_sign_in_bridge_conflict_returns_guidance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        assert link_plex(client).status_code == 200

        async def different_account(_token: str) -> PlexCloudAccount:
            return PlexCloudAccount(id=99, username="other account")

        monkeypatch.setattr(harness.plex, "account", different_account)
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == 409
        assert response.json() == {"detail": CONFLICT_GUIDANCE}


def test_account_logs_outcomes_without_private_values(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    caplog.set_level("INFO", logger="tasterr.account")
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        assert (
            client.post(
                "/api/v1/account/links/seerr", json={**LOCAL, "password": "wrong"}
            ).status_code
            == 401
        )
        assert link_plex(client).status_code == 200
        assert client.post("/api/v1/account/links/plex/unlink", json={}).status_code == 204
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 409
        assert client.post("/api/v1/account/delete", json={"confirm": "wrong"}).status_code == 422
        assert client.post("/api/v1/account/delete", json={"confirm": "Viewer"}).status_code == 204
    messages = [
        record.getMessage() for record in caplog.records if record.name == "tasterr.account"
    ]
    assert messages == [
        "account: link seerr refused",
        "account: create plex pin succeeded",
        "account: link plex succeeded",
        "account: unlink plex succeeded",
        "account: unlink seerr refused",
        "account: delete refused",
        "account: delete succeeded",
    ]


def test_new_links_evaluate_history_triggers(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str] = []

    def seerr(*_args: object) -> None:
        calls.append("seerr")

    def plex(*args: object) -> None:
        if args[-1] is not None:
            calls.append("plex")

    monkeypatch.setattr("tasterr.api.taste.schedule_seed", seerr)
    monkeypatch.setattr("tasterr.api.taste.schedule_plex_history", plex)
    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        login(client)
        calls.clear()
        assert link_plex(client).status_code == 200
        assert "plex" in calls
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 204
        calls.clear()
        assert client.post("/api/v1/account/links/seerr", json=LOCAL).status_code == 204
        assert "seerr" in calls


@pytest.mark.parametrize("deleting", [False, True])
async def test_unlink_and_delete_cancel_syncs_and_block_home_scheduling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    deleting: bool,
) -> None:
    from tests.test_browse_api import FakeCatalog

    from tasterr.api.availability import get_availability
    from tasterr.api.catalog import get_catalog
    from tasterr.cache import Cache
    from tasterr.catalog.availability import AvailabilityService
    from tasterr.catalog.service import CatalogService

    harness = _harness(tmp_path)
    harness.plex.token = PLEX_TOKEN
    harness.app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, FakeCatalog())
    harness.app.dependency_overrides[get_availability] = lambda: AvailabilityService(None, Cache())
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    settings.tmdb_api_key = SecretStr("tmdb-key")
    scheduled: list[object] = []
    reservations: list[int] = []

    def record_reservation(seeding: set[int], user_id: int) -> bool:
        reservations.append(user_id)
        return reserve_seed(seeding, user_id)

    async def unexpected(*_args: object, **_kwargs: object) -> None:
        scheduled.append(True)

    monkeypatch.setattr("tasterr.api.taste.seed_in_background", unexpected)
    monkeypatch.setattr("tasterr.api.taste.import_plex_history", unexpected)
    monkeypatch.setattr("tasterr.api.taste.reserve_seed", record_reservation)
    cancelled = asyncio.Event()
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
    ):
        await client.post("/api/v1/auth/local", json=LOCAL)
        created = await client.post("/api/v1/account/links/plex/pin")
        await client.post(
            "/api/v1/account/links/plex/pin/poll", json={"pin_id": created.json()["pin_id"]}
        )
        await asyncio.gather(
            *harness.app.state.seed_tasks.values(),
            *harness.app.state.plex_history_tasks.values(),
        )
        scheduled.clear()
        reservations.clear()

        async def hanging() -> None:
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                assert 1 in harness.app.state.plex_history_resets
                harness.app.state.plex_history_tasks.pop(1)
                assert (await client.get("/api/v1/home")).status_code == 200
                assert harness.app.state.seed_tasks == {}
                assert harness.app.state.plex_history_tasks == {}
                assert scheduled == []
                assert reservations == []
                cancelled.set()
                raise

        task = asyncio.create_task(hanging())
        harness.app.state.plex_history_tasks[1] = task
        await asyncio.sleep(0)
        if deleting:
            result = await client.post("/api/v1/account/delete", json={"confirm": "Viewer"})
        else:
            result = await client.post(
                "/api/v1/account/links/plex/unlink", json={"delete_history": True}
            )
        assert result.status_code == 204
        assert cancelled.is_set() and task.cancelled()
        assert harness.app.state.plex_history_tasks == {}

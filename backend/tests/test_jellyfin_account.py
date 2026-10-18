# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import db_call
from tests.test_jellyfin_auth import BODY, jellyfin_harness

from tasterr.auth.ratelimit import TokenBucket
from tasterr.db.models import LinkedAccount, Profile, Signal
from tasterr.recommend.store import record_signal
from tasterr.settings import Settings, get_settings

LOCAL = {"email": "viewer@example.test", "password": "password"}


@pytest.mark.parametrize("delete_history", [False, True])
def test_unlink_history_option_only_removes_jellyfin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, delete_history: bool
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr", seerr_api_key="key"
    )
    harness.upstream.seerr_status = 200
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200

        async def prepare(db: AsyncSession) -> None:
            for kind in ("watched_jellyfin", "watched_plex", "watchlist"):
                await record_signal(db, 1, "movie", 550, kind)
            db.add(Profile(user_id=1, vector="{}"))

        db_call(harness.db_path, prepare)
        assert (
            client.post(
                "/api/v1/account/links/jellyfin/unlink", json={"delete_history": delete_history}
            ).status_code
            == 204
        )

    async def verify(db: AsyncSession) -> None:
        kinds = set(await db.scalars(select(Signal.kind)))
        assert kinds == (
            {"watched_plex", "watchlist"}
            if delete_history
            else {"watched_jellyfin", "watched_plex", "watchlist"}
        )
        assert ((await db.get(Profile, 1)) is None) is delete_history

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("logout_status", [204, 503])
def test_link_authenticates_logs_out_and_relinks_in_place(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, logout_status: int
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr", seerr_api_key="key"
    )
    harness.upstream.seerr_status = 200
    harness.upstream.logout_status = logout_status
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/local", json=LOCAL).status_code == 200
        assert client.post("/api/v1/account/links/jellyfin", json=BODY).status_code == 204
        assert client.post("/api/v1/account/links/jellyfin", json=BODY).status_code == 204
        providers = client.get("/api/v1/account").json()["providers"]
        jellyfin = next(provider for provider in providers if provider["provider"] == "jellyfin")
        assert jellyfin["linked"] and jellyfin["can_unlink"] and jellyfin["available"]
    assert sum(request.url.path == "/Sessions/Logout" for request in harness.upstream.requests) == 2

    async def verify(db: AsyncSession) -> None:
        links = (
            await db.scalars(select(LinkedAccount).where(LinkedAccount.provider == "jellyfin"))
        ).all()
        assert len(links) == 1 and links[0].credential_enc is None

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("method", ["jellyfin", "seerr"])
@pytest.mark.parametrize("allowed", [False, True])
def test_both_link_forms_enforce_empty_password_before_any_upstream(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str, allowed: bool
) -> None:
    harness = jellyfin_harness(
        tmp_path,
        monkeypatch,
        jellyfin_allow_empty_password=allowed,
        seerr_internal_url="http://seerr",
        seerr_api_key="key",
    )
    harness.upstream.seerr_status = 200
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/local", json=LOCAL).status_code == 200
        harness.upstream.requests.clear()
        response = client.post(
            f"/api/v1/account/links/{method}", json={**BODY, "password": "", "method": "jellyfin"}
        )
        assert response.status_code == (204 if allowed else 401)
        assert bool(harness.upstream.requests) is allowed


@pytest.mark.parametrize("method", ["jellyfin", "seerr"])
def test_unconfigured_link_503_and_dormant_unlink_works(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr", seerr_api_key="key"
    )
    harness.upstream.seerr_status = 200
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/local", json=LOCAL).status_code == 200
        assert client.post("/api/v1/account/links/jellyfin", json=BODY).status_code == 204
        assert client.portal is not None

        async def finish_history() -> None:
            await asyncio.gather(*harness.app.state.jellyfin_history_tasks.values())

        client.portal.call(finish_history)
        settings = Settings.model_validate(
            {
                "tasterr_secret_key": "test-secret-key",
                "seerr_internal_url": "http://seerr",
                "seerr_api_key": "key",
            }
        )
        harness.app.dependency_overrides[get_settings] = lambda: settings
        harness.upstream.requests.clear()
        assert (
            client.post(
                f"/api/v1/account/links/{method}", json={**BODY, "method": "jellyfin"}
            ).status_code
            == 503
        )
        assert harness.upstream.requests == []
        assert client.post("/api/v1/account/links/jellyfin/unlink", json={}).status_code == 204


def test_seerr_jellyfin_method_links_and_clears_unlink_marker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr", seerr_api_key="key"
    )
    with TestClient(harness.app) as client:
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200
        harness.upstream.seerr_status = 200
        assert (
            client.post(
                "/api/v1/account/links/seerr", json={**BODY, "method": "jellyfin"}
            ).status_code
            == 204
        )
        assert client.post("/api/v1/account/links/seerr/unlink", json={}).status_code == 204
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200
        assert not next(
            p for p in client.get("/api/v1/account").json()["providers"] if p["provider"] == "seerr"
        )["linked"]
        assert (
            client.post(
                "/api/v1/account/links/seerr", json={**BODY, "method": "jellyfin"}
            ).status_code
            == 204
        )


@pytest.mark.parametrize("method", ["jellyfin", "seerr"])
def test_link_guards(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, method: str) -> None:
    harness = jellyfin_harness(
        tmp_path, monkeypatch, seerr_internal_url="http://seerr", seerr_api_key="key"
    )
    with TestClient(harness.app) as client:
        path = f"/api/v1/account/links/{method}"
        body = {**BODY, "method": "jellyfin"}
        assert client.post(path, json=body).status_code == 401
        assert client.post("/api/v1/auth/jellyfin", json=BODY).status_code == 200
        assert client.portal is not None

        async def finish_history() -> None:
            await asyncio.gather(*harness.app.state.jellyfin_history_tasks.values())

        client.portal.call(finish_history)
        harness.upstream.requests.clear()
        assert (
            client.post(path, json=body, headers={"Sec-Fetch-Site": "cross-site"}).status_code
            == 403
        )
        harness.app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)
        assert client.post(path, json=body).status_code == 429
        assert harness.upstream.requests == []

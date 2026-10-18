# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import db_call
from tests.test_auth_api import PLEX_TOKEN, _harness, _poll_pin, _start_pin_login

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexResourceAccess
from tasterr.db.models import LinkedAccount, User, UserSession


async def assert_empty(db: AsyncSession) -> None:
    for model in (User, LinkedAccount, UserSession):
        assert (await db.scalars(select(model))).all() == []


@pytest.mark.parametrize("owner", [False, True])
def test_plex_admin_without_seerr_reuses_gate_read(tmp_path: Path, owner: bool) -> None:
    harness = _harness(tmp_path, configured=False, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    harness.plex.resource_list = [PlexResourceAccess(clientIdentifier="pinned", owned=owner)]
    with TestClient(harness.app) as client:
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == 200
        assert response.json()["user"]["is_admin"] is owner
        assert harness.plex.resource_calls == 1


@pytest.mark.parametrize("pinned", [False, True])
@pytest.mark.parametrize("seerr", [False, True])
@pytest.mark.parametrize("secret", [False, True])
def test_gate_configuration_table(tmp_path: Path, pinned: bool, seerr: bool, secret: bool) -> None:
    harness = _harness(
        tmp_path, configured=seerr, with_secret=secret, server_id="pinned" if pinned else None
    )
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        methods = client.get("/api/v1/auth/methods")
        assert methods.status_code == 200
        assert methods.json() == {"plex": secret and (pinned or seerr), "seerr": secret and seerr}
        assert all(type(value) is bool for value in methods.json().values())
        assert harness.plex.resource_calls == harness.seerr.login_calls == 0
        created = client.post("/api/v1/auth/plex/pin")
        if secret and (pinned or seerr):
            assert created.status_code == 200
            response = _poll_pin(client, created.json()["pin_id"])
            assert response.status_code == 200
            assert harness.plex.resource_calls == int(pinned)
            assert harness.seerr.login_calls == int(seerr)
        else:
            assert created.status_code == 503
            db_call(harness.db_path, assert_empty)
        if not (secret and seerr):
            assert (
                client.post("/api/v1/auth/local", json={"email": "a", "password": "b"}).status_code
                == 503
            )


@pytest.mark.parametrize("existing", [False, True])
def test_server_gate_refuses_missing_or_revoked_access(tmp_path: Path, existing: bool) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        if existing:
            assert _poll_pin(client, _start_pin_login(client)).status_code == 200
        harness.plex.resource_list = []
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == 401
        assert response.json() == {"detail": "Sign-in failed"}
        assert "set-cookie" not in response.headers
        assert harness.seerr.login_calls == int(existing)
    if not existing:
        db_call(harness.db_path, assert_empty)


def test_server_gate_ignores_seerr_refusal_and_offline_pms(tmp_path: Path) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = "refused-by-seerr"
    with TestClient(harness.app) as client:
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == 200
        assert response.json()["user"]["display_name"] == "plex-viewer"
        assert harness.plex.resource_calls == 1

    async def verify(db: AsyncSession) -> None:
        assert [link.provider for link in (await db.scalars(select(LinkedAccount))).all()] == [
            "plex"
        ]

    db_call(harness.db_path, verify)


@pytest.mark.parametrize("existing", [False, True])
def test_seerr_outage_blocks_only_new_user(tmp_path: Path, existing: bool) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    with TestClient(harness.app) as client:
        first_id = None
        if existing:
            first = _poll_pin(client, _start_pin_login(client))
            assert first.status_code == 200
            first_id = first.json()["user"]["id"]
        harness.seerr.down = True
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == (200 if existing else 502)
        if existing:
            assert response.json()["user"]["id"] == first_id
        else:
            assert "set-cookie" not in response.headers
            db_call(harness.db_path, assert_empty)


@pytest.mark.parametrize("error", [UpstreamRejected(401), UpstreamUnavailable("outage")])
def test_resource_failure_fails_closed(tmp_path: Path, error: Exception) -> None:
    harness = _harness(tmp_path, server_id="pinned")
    harness.plex.token = PLEX_TOKEN
    harness.plex.resource_error = error
    with TestClient(harness.app) as client:
        response = _poll_pin(client, _start_pin_login(client))
        assert response.status_code == 502
        assert response.json() == {"detail": "Sign-in service unavailable"}
        assert harness.seerr.login_calls == 0
        db_call(harness.db_path, assert_empty)

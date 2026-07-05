"""Live Seerr auth contract tests — run manually via `just test-live`.

Requires a reachable Seerr instance and a *local* account, via env (values
are never committed; see SECURITY.md working notes):

    TASTERR_LIVE_SEERR_URL       e.g. http://192.0.2.10:5055
    TASTERR_LIVE_SEERR_EMAIL     local-account email
    TASTERR_LIVE_SEERR_PASSWORD  local-account password

Validates the contract the recorded fixtures in tests/test_clients_seerr.py
assume — including the auth spike's one deferred question (local login) and
its 403-not-401 deviation — and prints the Seerr version tested. The Plex
login path needs interactive PIN approval, so it stays covered by the spike
findings and the fixture suite; known-good version: 3.3.0.
"""

import os

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected
from tasterr.clients.seerr import SeerrAuthClient

pytestmark = pytest.mark.live

URL = os.environ.get("TASTERR_LIVE_SEERR_URL", "").rstrip("/")
EMAIL = os.environ.get("TASTERR_LIVE_SEERR_EMAIL", "")
PASSWORD = os.environ.get("TASTERR_LIVE_SEERR_PASSWORD", "")

requires_env = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD),
    reason="TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD not set",
)


@requires_env
async def test_local_login_contract_and_version() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        status = await http.get(f"{URL}/api/v1/status")
        assert status.status_code == 200
        version = status.json().get("version")

        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)

        assert login.cookie.startswith("connect.sid=")
        assert login.user.id > 0
        assert isinstance(login.user.permissions, int)
        assert login.user.resolved_display_name

        me = await http.get(f"{URL}/api/v1/auth/me", headers={"Cookie": login.cookie})
        assert me.status_code == 200
        assert me.json()["id"] == login.user.id

    print(f"\nSeerr version tested: {version}")


@requires_env
async def test_invalid_session_returns_403_not_401() -> None:
    """The spike's recorded deviation from the original SPEC assumption."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        response = await http.get(
            f"{URL}/api/v1/auth/me",
            headers={"Cookie": "connect.sid=s%3Anot-a-real-session"},
        )

    assert response.status_code == 403


@requires_env
async def test_wrong_credentials_are_rejected() -> None:
    async with httpx.AsyncClient(timeout=10.0) as http:
        with pytest.raises(UpstreamRejected):
            await SeerrAuthClient(http, URL).login_local(EMAIL, "definitely-not-the-password")

"""Live Seerr auth contract tests — run manually via `just test-live`.

Requires a reachable Seerr instance and a *local* account, via env (values
are never committed; see SECURITY.md working notes):

    TASTERR_LIVE_SEERR_URL       e.g. http://192.0.2.10:5055
    TASTERR_LIVE_SEERR_EMAIL     local-account email
    TASTERR_LIVE_SEERR_PASSWORD  local-account password
    TASTERR_LIVE_PLEX_TOKEN      optional: a Plex auth token, to also validate
                                 the /auth/plex stored-token path (the exact
                                 call M3's silent re-auth depends on)

Validates the contract the recorded fixtures in tests/test_clients_seerr.py
assume — including the auth spike's one deferred question (local login) and
its 403-not-401 deviation — and prints the Seerr version tested. The
interactive PIN half of the Plex flow still needs a human at plex.tv; supply
a token obtained from any signed-in Plex client to cover the Seerr side.
Known-good version: 3.3.0.
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
PLEX_TOKEN = os.environ.get("TASTERR_LIVE_PLEX_TOKEN", "")

requires_env = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD),
    reason="TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD not set",
)

requires_plex_token = pytest.mark.skipif(
    not (URL and PLEX_TOKEN),
    reason="TASTERR_LIVE_SEERR_URL/TASTERR_LIVE_PLEX_TOKEN not set",
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


@requires_plex_token
async def test_plex_stored_token_login_contract() -> None:
    """Seerr accepts a stored Plex token at /auth/plex — the silent re-auth
    primitive M3 builds on, and the non-interactive half of the Plex flow."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        login = await SeerrAuthClient(http, URL).login_plex(PLEX_TOKEN)

        assert login.cookie.startswith("connect.sid=")
        assert login.user.id > 0
        assert isinstance(login.user.permissions, int)
        assert login.user.resolved_display_name

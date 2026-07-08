"""Live Seerr contract tests — run manually via `just test-live`.

Requires a reachable Seerr instance and a *local* account, via env (values
are never committed; see SECURITY.md working notes):

    TASTERR_LIVE_SEERR_URL       e.g. http://192.0.2.10:5055
    TASTERR_LIVE_SEERR_EMAIL     local-account email
    TASTERR_LIVE_SEERR_PASSWORD  local-account password
    TASTERR_LIVE_SEERR_API_KEY   optional: the global API key, to validate the
                                 availability read contract (M3 badges)
    TASTERR_LIVE_AVAILABLE_TMDB_ID optional: a tmdb id the operator knows is in the
                                 library — proves the *available-title* mediaInfo
                                 shape (the Fight Club smoke test alone can't, since
                                 a given library may hold no record for it)
    TASTERR_LIVE_PLEX_TOKEN      optional: a Plex auth token, to also validate
                                 the /auth/plex stored-token path (the exact
                                 call M3's silent re-auth depends on)
    TASTERR_LIVE_REQUEST_TMDB_ID optional: a movie tmdb id the operator is willing
                                 to actually request — enables the (invasive)
                                 request-as-user attribution test, which creates a
                                 real request in Seerr and best-effort deletes it

Validates the contract the recorded fixtures in tests/test_clients_seerr.py
assume — auth (local login, the 403-not-401 deviation), M3 availability reads, and
request-as-user attribution — and prints the Seerr version tested. The interactive
PIN half of the Plex flow still needs a human at plex.tv; supply a token obtained
from any signed-in Plex client to cover the Seerr side. Known-good version: 3.3.0.

The M3 403 silent re-auth ladder is validated by its *primitives* here — a stored
token minting a fresh cookie (test_plex_stored_token_login_contract), an invalid
session returning 403 (test_request_with_invalid_session_is_403), and a valid
cookie creating an attributed request (test_request_as_user_attribution_and_cleanup);
their orchestration into "403 → re-auth → retry once" is covered by the mocked unit
tests in tests/test_request_api.py (forcing a live session expiry mid-flight would
be invasive and non-deterministic).
"""

import os

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient

pytestmark = pytest.mark.live

URL = os.environ.get("TASTERR_LIVE_SEERR_URL", "").rstrip("/")
EMAIL = os.environ.get("TASTERR_LIVE_SEERR_EMAIL", "")
PASSWORD = os.environ.get("TASTERR_LIVE_SEERR_PASSWORD", "")
API_KEY = os.environ.get("TASTERR_LIVE_SEERR_API_KEY", "")
AVAILABLE_TMDB_ID = os.environ.get("TASTERR_LIVE_AVAILABLE_TMDB_ID", "")
PLEX_TOKEN = os.environ.get("TASTERR_LIVE_PLEX_TOKEN", "")
REQUEST_TMDB_ID = os.environ.get("TASTERR_LIVE_REQUEST_TMDB_ID", "")

# A stable, always-known movie (Fight Club) for the read smoke test.
KNOWN_MOVIE_TMDB_ID = 550

requires_env = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD),
    reason="TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD not set",
)

requires_url = pytest.mark.skipif(not URL, reason="TASTERR_LIVE_SEERR_URL not set")

requires_api_key = pytest.mark.skipif(
    not (URL and API_KEY),
    reason="TASTERR_LIVE_SEERR_URL/TASTERR_LIVE_SEERR_API_KEY not set",
)

requires_available = pytest.mark.skipif(
    not (URL and API_KEY and AVAILABLE_TMDB_ID),
    reason="TASTERR_LIVE_SEERR_URL/API_KEY/TASTERR_LIVE_AVAILABLE_TMDB_ID not set",
)

requires_request = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD and REQUEST_TMDB_ID),
    reason="TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD/TASTERR_LIVE_REQUEST_TMDB_ID not set",
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


@requires_api_key
async def test_availability_read_smoke_and_not_in_library() -> None:
    """A well-known title parses without error (its `mediaInfo` may be absent if the
    library holds no record for it), and a bogus id is a known not-in-library (None),
    never an error. The *available-title* shape is proven separately below."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = SeerrClient(http, URL, API_KEY)

        info = await client.media_status("movie", KNOWN_MOVIE_TMDB_ID)
        if info is not None:
            assert isinstance(info.status, int)

        assert await client.media_status("movie", 999_999_999) is None


@requires_available
async def test_available_title_has_a_media_record() -> None:
    """Proves the available-title contract: an operator-supplied in-library id
    returns a real `mediaInfo` with a valid MediaStatus code (1-5)."""
    tmdb_id = int(AVAILABLE_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        info = await SeerrClient(http, URL, API_KEY).media_status("movie", tmdb_id)

        assert info is not None, "expected a media record for the supplied available id"
        assert info.status in range(1, 6)  # Seerr MediaStatus is 1-5


@requires_url
async def test_request_with_invalid_session_is_403() -> None:
    """The request-side 403 the re-auth ladder keys on — validated without side
    effects: an invalid session is rejected before anything is created."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = SeerrClient(http, URL, API_KEY or "unused-for-requests")
        with pytest.raises(UpstreamRejected) as excinfo:
            await client.create_request(
                "connect.sid=s%3Anot-a-real-session", "movie", KNOWN_MOVIE_TMDB_ID
            )
        assert excinfo.value.status_code == 403


@requires_request
async def test_request_as_user_attribution_and_cleanup() -> None:
    """The M3 milestone bar — a request lands in Seerr attributed to the member.
    Invasive: creates a real request, then best-effort deletes it *without* trusting
    the delete `204` while the request may be mid-dispatch (spike finding)."""
    tmdb_id = int(REQUEST_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)

        created = await http.post(
            f"{URL}/api/v1/request",
            headers={"Cookie": login.cookie},
            json={"mediaType": "movie", "mediaId": tmdb_id},
        )
        assert created.status_code in (200, 201)
        payload = created.json()
        assert payload["requestedBy"]["id"] == login.user.id  # attributed to the member

        request_id = payload.get("id")
        if request_id is not None:  # cleanup only; not treated as authoritative
            await http.delete(
                f"{URL}/api/v1/request/{request_id}", headers={"Cookie": login.cookie}
            )

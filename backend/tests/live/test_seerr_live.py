"""Live Seerr contract tests — run manually via `just test-live`.

Requires a reachable Seerr instance and a *local* account, via env (values
are never committed; see SECURITY.md working notes):

    TASTERR_LIVE_SEERR_URL       e.g. http://seerr.example.test:5055
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
assume — auth (local login, the 403-not-401 deviation), M3 availability reads,
request-as-user attribution, and the M4 request-history read the cold-start seed
consumes — and prints the Seerr version tested. The interactive PIN half of the
Plex flow still needs a human at plex.tv; supply a token obtained from any
signed-in Plex client to cover the Seerr side. Known-good version: 3.3.0.

The M3 403 silent re-auth ladder is validated by its *primitives* here — a stored
token minting a fresh cookie (test_plex_stored_token_login_contract), an invalid
session returning 403 (test_request_with_invalid_session_is_403), and a valid
cookie creating an attributed request (test_request_as_user_attribution_and_cleanup);
their orchestration into "403 → re-auth → retry once" is covered by the mocked unit
tests in tests/test_request_api.py (forcing a live session expiry mid-flight would
be invasive and non-deterministic).
"""

import asyncio
import os

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field

from tasterr.catalog.availability import NOT_REQUESTED, to_availability
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

requires_availability = pytest.mark.skipif(
    not (URL and API_KEY and REQUEST_TMDB_ID),
    reason="TASTERR_LIVE_SEERR_URL/API_KEY/TASTERR_LIVE_REQUEST_TMDB_ID not set",
)

requires_available = pytest.mark.skipif(
    not (URL and API_KEY and AVAILABLE_TMDB_ID),
    reason="TASTERR_LIVE_SEERR_URL/API_KEY/TASTERR_LIVE_AVAILABLE_TMDB_ID not set",
)

requires_request = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD and API_KEY and REQUEST_TMDB_ID),
    reason=("TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD/API_KEY/TASTERR_LIVE_REQUEST_TMDB_ID not set"),
)

requires_plex_token = pytest.mark.skipif(
    not (URL and PLEX_TOKEN),
    reason="TASTERR_LIVE_SEERR_URL/TASTERR_LIVE_PLEX_TOKEN not set",
)

requires_history = pytest.mark.skipif(
    not (URL and EMAIL and PASSWORD and API_KEY),
    reason="TASTERR_LIVE_SEERR_URL/EMAIL/PASSWORD/TASTERR_LIVE_SEERR_API_KEY not set",
)


class _CleanupMedia(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    tmdb_id: int | None = Field(default=None, alias="tmdbId")


class _CleanupRequest(BaseModel):
    id: int
    media: _CleanupMedia | None = None


class _CleanupPage(BaseModel):
    results: list[_CleanupRequest]


async def _request_id_for_title(http: httpx.AsyncClient, user_id: int, tmdb_id: int) -> int | None:
    response = await http.get(
        f"{URL}/api/v1/request",
        params={"take": 50, "skip": 0, "requestedBy": user_id, "sort": "added"},
        headers={"X-Api-Key": API_KEY, "Accept": "application/json"},
    )
    response.raise_for_status()
    page = _CleanupPage.model_validate(response.json())
    for row in page.results:
        if row.media is not None and row.media.tmdb_id == tmdb_id:
            return row.id
    return None


async def _delete_request_and_verify(
    http: httpx.AsyncClient,
    cookie: str,
    user_id: int,
    tmdb_id: int,
    request_id: int | None,
) -> None:
    client = SeerrClient(http, URL, API_KEY)
    for _ in range(5):
        request_id = request_id or await _request_id_for_title(http, user_id, tmdb_id)
        if request_id is not None:
            deleted = await http.delete(
                f"{URL}/api/v1/request/{request_id}", headers={"Cookie": cookie}
            )
            assert deleted.status_code in (200, 204, 404)
            request_id = None

        history = await client.list_requests(user_id)
        if all(item.tmdb_id != tmdb_id for item in history):
            return
        await asyncio.sleep(1)
    pytest.fail("disposable live request remained after cleanup")


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


@requires_availability
async def test_availability_read_smoke_and_not_in_library() -> None:
    """A well-known title parses without error, and the operator-supplied valid,
    unrequested title maps to known `not_requested` whether Seerr omits `mediaInfo`
    or retains a status-1 record. The *available-title* shape is proven separately."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        client = SeerrClient(http, URL, API_KEY)

        info = await client.media_status("movie", KNOWN_MOVIE_TMDB_ID)
        if info is not None:
            assert isinstance(info.status, int)

        unrequested = await client.media_status("movie", int(REQUEST_TMDB_ID))
        assert to_availability(unrequested) == NOT_REQUESTED


@requires_available
async def test_available_title_has_a_media_record() -> None:
    """Proves the available-title contract: an operator-supplied in-library id
    returns a real `mediaInfo` whose MediaStatus maps to available."""
    tmdb_id = int(AVAILABLE_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        info = await SeerrClient(http, URL, API_KEY).media_status("movie", tmdb_id)

        assert info is not None, "expected a media record for the supplied available id"
        assert to_availability(info).status == "available"


@requires_history
async def test_request_history_read_contract() -> None:
    """The M4 cold-start seed's read: the global key + explicit `requestedBy`
    filter returns only the member's requests, paginated, with the fields the
    seed consumes (tmdb id, movie/tv type, created-at). Read-only."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)

        # Raw shape first: the filter is honored — every row is the member's —
        # and pagination params are accepted.
        raw = await http.get(
            f"{URL}/api/v1/request",
            params={"take": 20, "skip": 0, "requestedBy": login.user.id, "sort": "added"},
            headers={"X-Api-Key": API_KEY, "Accept": "application/json"},
        )
        assert raw.status_code == 200
        body = raw.json()
        assert "results" in body
        for row in body["results"]:
            assert row["requestedBy"]["id"] == login.user.id

        # Then the typed client parse the seed depends on.
        history = await SeerrClient(http, URL, API_KEY).list_requests(login.user.id)
        for item in history:
            assert item.media_type in ("movie", "tv")
            assert item.tmdb_id > 0
            assert item.created_at.tzinfo is None  # naive UTC, the DB convention


@requires_history
async def test_request_history_second_page_when_data_exists() -> None:
    """Exercise a real deeper page only when the operator account has enough data."""
    async with httpx.AsyncClient(timeout=10.0) as http:
        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)
        headers = {"X-Api-Key": API_KEY, "Accept": "application/json"}
        params = {
            "take": 50,
            "skip": 50,
            "requestedBy": login.user.id,
            "sort": "added",
        }
        response = await http.get(f"{URL}/api/v1/request", params=params, headers=headers)

        assert response.status_code == 200
        results = response.json()["results"]
        if not results:
            pytest.skip("live history pagination precondition absent")
        for row in results:
            assert row["requestedBy"]["id"] == login.user.id


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
    Invasive: creates a real request, deletes it, then verifies it disappears from
    history instead of trusting the delete response while dispatch may still run."""
    tmdb_id = int(REQUEST_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)
        info = await SeerrClient(http, URL, API_KEY).media_status("movie", tmdb_id)
        assert to_availability(info) == NOT_REQUESTED

        created_may_have_succeeded = False
        request_id: int | None = None
        try:
            created = await http.post(
                f"{URL}/api/v1/request",
                headers={"Cookie": login.cookie},
                json={"mediaType": "movie", "mediaId": tmdb_id},
            )
            created_may_have_succeeded = created.is_success
            assert created.status_code in (200, 201)
            payload = created.json()
            candidate_id = payload.get("id")
            if isinstance(candidate_id, int):
                request_id = candidate_id
            assert request_id is not None
            assert payload["requestedBy"]["id"] == login.user.id
        finally:
            if created_may_have_succeeded:
                await _delete_request_and_verify(
                    http, login.cookie, login.user.id, tmdb_id, request_id
                )

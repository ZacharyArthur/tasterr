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

from tasterr.catalog.availability import to_availability
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
REQUEST_4K_TMDB_ID = os.environ.get("TASTERR_LIVE_REQUEST_4K_TMDB_ID", "")

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
    media_type: str = Field(default="", alias="mediaType")


class _CleanupRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: int
    is_4k: bool = Field(alias="is4k")
    media: _CleanupMedia | None = None


class _CleanupPage(BaseModel):
    results: list[_CleanupRequest]


async def _request_id_for_title(
    http: httpx.AsyncClient, user_id: int, tmdb_id: int, *, is_4k: bool = False
) -> int | None:
    response = await http.get(
        f"{URL}/api/v1/request",
        params={"take": 50, "skip": 0, "requestedBy": user_id, "sort": "added"},
        headers={"X-Api-Key": API_KEY, "Accept": "application/json"},
    )
    response.raise_for_status()
    page = _CleanupPage.model_validate(response.json())
    for row in page.results:
        if (
            row.media is not None
            and row.media.tmdb_id == tmdb_id
            and row.media.media_type == "movie"
            and row.is_4k == is_4k
        ):
            return row.id
    return None


async def _delete_request_and_verify(
    http: httpx.AsyncClient,
    cookie: str,
    user_id: int,
    tmdb_id: int,
    request_id: int | None,
    *,
    is_4k: bool = False,
) -> None:
    for _ in range(5):
        request_id = request_id or await _request_id_for_title(http, user_id, tmdb_id, is_4k=is_4k)
        if request_id is not None:
            deleted = await http.delete(
                f"{URL}/api/v1/request/{request_id}", headers={"Cookie": cookie}
            )
            assert deleted.status_code in (200, 204, 404)
            request_id = None

        if await _request_id_for_title(http, user_id, tmdb_id, is_4k=is_4k) is None:
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
        availability = to_availability(unrequested)
        assert availability.status == "not_requested"
        assert availability.known


@requires_available
async def test_available_title_has_a_media_record() -> None:
    """Proves the playback-link contract when the operator supplies a Plex-backed
    in-library title; other media-server backends skip without exposing links."""
    tmdb_id = int(AVAILABLE_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        info = await SeerrClient(http, URL, API_KEY).media_status("movie", tmdb_id)

        assert info is not None, "expected a media record for the supplied available id"
        availability = to_availability(info)
        assert availability.status in ("partial", "available")
        if availability.playback is None:
            pytest.skip("available title has no Plex playback links")
        assert availability.playback.regular is not None or availability.playback.four_k is not None


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
        availability = to_availability(info)
        assert availability.status == "not_requested"
        assert availability.known

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


@requires_request
@pytest.mark.parametrize("is_4k", [False, True])
async def test_request_destination_override_stores_chosen_destination(is_4k: bool) -> None:
    """Opt-in persistence contract; downstream delivery remains operator-verified.

    The separate 4K title is disposable too: deleting a request does not undo
    an autoapproved download. Administrator rules can rewrite supplied choices.
    """
    if is_4k and not REQUEST_4K_TMDB_ID:
        pytest.skip("TASTERR_LIVE_REQUEST_4K_TMDB_ID not set")
    tmdb_id = int(REQUEST_4K_TMDB_ID if is_4k else REQUEST_TMDB_ID)
    async with httpx.AsyncClient(timeout=10.0) as http:
        version_response = await http.get(f"{URL}/api/v1/status")
        version_response.raise_for_status()
        version = version_response.json().get("version")
        assert isinstance(version, str)
        print(f"\nSeerr version tested: {version}")
        login = await SeerrAuthClient(http, URL).login_local(EMAIL, PASSWORD)
        if not login.user.can_override or not login.user.can_request("movie", is_4k=is_4k):
            pytest.skip("operator account lacks variant or advanced permission")
        client = SeerrClient(http, URL, API_KEY)
        servers = [server for server in await client.list_servers("movie") if server.is_4k == is_4k]
        if not servers:
            pytest.skip("operator has no configured destination for this variant")
        server = next((server for server in servers if not server.is_default), servers[0])
        detail = await client.server_destinations("movie", server.id)
        if not detail.profiles or not detail.root_folders:
            pytest.skip("chosen destination has no profiles/root folders")
        profile = next(
            (p for p in detail.profiles if p.id != server.active_profile_id), detail.profiles[0]
        )
        folder = next(
            (f for f in detail.root_folders if f.path != server.active_directory),
            detail.root_folders[0],
        )
        info = await client.media_status("movie", tmdb_id)
        code = (info.status_4k if is_4k else info.status) if info else 0
        assert code not in (2, 3, 4, 5), "disposable title variant must be unrequested"

        request_id: int | None = None
        try:
            await client.create_request(
                login.cookie,
                "movie",
                tmdb_id,
                is_4k=is_4k,
                server_id=server.id,
                profile_id=profile.id,
                root_folder=folder.path,
            )
            request_id = await _request_id_for_title(http, login.user.id, tmdb_id, is_4k=is_4k)
            assert request_id is not None, "created request must be visible in member history"
            saved = await http.get(
                f"{URL}/api/v1/request/{request_id}", headers={"X-Api-Key": API_KEY}
            )
            saved.raise_for_status()
            payload = saved.json()
            if payload["requestedBy"]["id"] != login.user.id:
                pytest.fail("stored request attribution differs")
            if payload["is4k"] is not is_4k:
                pytest.fail("stored request variant differs")
            if payload["serverId"] != server.id:
                pytest.fail("stored request server differs; administrator rules may rewrite it")
            if payload["profileId"] != profile.id:
                pytest.fail("stored request profile differs; administrator rules may rewrite it")
            if payload["rootFolder"] != folder.path:
                pytest.fail("stored request folder differs; administrator rules may rewrite it")
        finally:
            # A timeout can occur after creation; lookup/cleanup must still run.
            await _delete_request_and_verify(
                http, login.cookie, login.user.id, tmdb_id, request_id, is_4k=is_4k
            )

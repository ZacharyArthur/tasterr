import json
from collections.abc import Callable

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient, SeerrUser

BASE_URL = "http://seerr:5055"

# Shape from the auth spike (docs/SEERR-AUTH-SPIKE.md) against Seerr 3.3.0,
# values redacted. Unknown fields must be ignored, not break parsing.
USER_FIXTURE = {
    "id": 1,
    "displayName": "Viewer",
    "plexUsername": "plex-viewer",
    "email": "owner@example.com",
    "avatar": "https://plex.tv/users/abc/avatar",
    "permissions": 2,
    "movieQuotaLimit": None,
    "createdAt": "2024-01-01T00:00:00.000Z",
}
COOKIE_HEADER = "connect.sid=s%3Aredacted.sig; Path=/; HttpOnly; SameSite=Lax"


def _client(handler: Callable[[httpx.Request], httpx.Response]) -> SeerrAuthClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SeerrAuthClient(http, BASE_URL)


async def test_login_plex_returns_user_and_cookie() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert str(request.url) == f"{BASE_URL}/api/v1/auth/plex"
        assert json.loads(request.read()) == {"authToken": "plex-token"}
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    login = await _client(handler).login_plex("plex-token")

    assert login.user.id == 1
    assert login.user.permissions == 2
    assert login.user.resolved_display_name == "Viewer"
    assert login.cookie == "connect.sid=s%3Aredacted.sig"


async def test_login_local_forwards_credentials_verbatim() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/auth/local"
        assert json.loads(request.read()) == {"email": "a@b.c", "password": "hunter2"}
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    login = await _client(handler).login_local("a@b.c", "hunter2")

    assert login.user.id == 1


async def test_rejection_is_typed_with_status() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": 403, "error": "You do not have permission"})

    with pytest.raises(UpstreamRejected) as excinfo:
        await _client(handler).login_local("a@b.c", "wrong")
    assert excinfo.value.status_code == 403


async def test_server_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_transport_error_drops_cause_and_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _client(handler).login_plex("plex-token")

    # The internal Seerr URL rides in the request the httpx error carries; the
    # fixed message and dropped __cause__ keep it out of both the message and the
    # exception chain an error tracker would capture.
    assert BASE_URL not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_missing_session_cookie_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=USER_FIXTURE)  # no Set-Cookie

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_unexpected_shape_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"totally": "unexpected"}, headers={"set-cookie": COOKIE_HEADER}
        )

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).login_plex("plex-token")


async def test_no_browser_headers_are_forwarded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        assert "x-api-key" not in request.headers  # admin key never rides user flows
        return httpx.Response(200, json=USER_FIXTURE, headers={"set-cookie": COOKIE_HEADER})

    await _client(handler).login_plex("plex-token")


def test_display_name_fallback_chain() -> None:
    assert SeerrUser(id=9).resolved_display_name == "user-9"
    assert SeerrUser(id=9, email="e@x.y").resolved_display_name == "e@x.y"
    assert (
        SeerrUser.model_validate(
            {"id": 9, "email": "e@x.y", "plexUsername": "px"}
        ).resolved_display_name
        == "px"
    )


# ── SeerrClient: availability reads (global API key) ─────────────────────────


def _media_client(handler: Callable[[httpx.Request], httpx.Response]) -> SeerrClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SeerrClient(http, BASE_URL, "seerr-api-key")


async def test_probe_uses_global_key_and_parses_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/status"
        assert request.headers["x-api-key"] == "seerr-api-key"
        return httpx.Response(200, json={"version": "3.3.0", "ignored": "x"})

    await _media_client(handler).probe()


async def test_probe_failure_is_generic() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("http://internal-secret", request=request)

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _media_client(handler).probe()

    assert "internal-secret" not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


async def test_media_status_parses_movie_mediainfo() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/movie/42"
        assert request.headers["x-api-key"] == "seerr-api-key"
        assert "cookie" not in request.headers  # user cookie never rides a read
        return httpx.Response(200, json={"id": 42, "mediaInfo": {"status": 5}})

    info = await _media_client(handler).media_status("movie", 42)

    assert info is not None
    assert info.status == 5


@pytest.mark.parametrize("web_field", ["plexUrl", "mediaUrl"])
async def test_media_status_accepts_both_seerr_playback_link_aliases(web_field: str) -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "mediaInfo": {
                    "status": 5,
                    web_field: "https://app.plex.tv/desktop/#!/details",
                    "iOSPlexUrl": "plex://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F42",
                    "ignoredFutureField": "safe to drop",
                }
            },
        )

    info = await _media_client(handler).media_status("movie", 42)

    assert info is not None
    assert info.web_url == "https://app.plex.tv/desktop/#!/details"
    assert info.app_url == "plex://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F42"


async def test_media_status_parses_4k_playback_fields() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "mediaInfo": {
                    "status": 1,
                    "status4k": 5,
                    "mediaUrl4k": "https://app.plex.tv/desktop/#!/4k-details",
                    "iOSPlexUrl4k": "plex://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F84",
                }
            },
        )

    info = await _media_client(handler).media_status("movie", 42)

    assert info is not None
    assert info.status_4k == 5
    assert info.web_url_4k == "https://app.plex.tv/desktop/#!/4k-details"
    assert info.app_url_4k == "plex://preplay/?metadataKey=%2Flibrary%2Fmetadata%2F84"


async def test_media_status_parses_tv_per_season() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "id": 7,
                "mediaInfo": {
                    "status": 4,
                    "seasons": [
                        {"seasonNumber": 1, "status": 5},
                        {"seasonNumber": 2, "status": 2},
                    ],
                },
            },
        )

    info = await _media_client(handler).media_status("tv", 7)

    assert info is not None
    assert info.status == 4
    assert [(s.season_number, s.status) for s in info.seasons] == [(1, 5), (2, 2)]


async def test_media_status_404_is_none_not_error() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "not found"})

    assert await _media_client(handler).media_status("movie", 1) is None


async def test_media_status_absent_mediainfo_is_none() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"id": 1})  # known title, never requested

    assert await _media_client(handler).media_status("movie", 1) is None


async def test_media_status_server_error_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(UpstreamUnavailable):
        await _media_client(handler).media_status("movie", 1)


async def test_media_status_timeout_is_unavailable() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("timed out", request=request)

    with pytest.raises(UpstreamUnavailable):
        await _media_client(handler).media_status("movie", 1)


async def test_media_status_error_drops_url_and_cause() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _media_client(handler).media_status("movie", 1)

    assert BASE_URL not in str(excinfo.value)
    assert excinfo.value.__cause__ is None


# ── SeerrClient: request-as-user (per-user cookie) ───────────────────────────


async def test_create_request_movie_uses_cookie_and_returns_status() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/request"
        assert request.headers["cookie"] == "connect.sid=abc"
        assert "x-api-key" not in request.headers  # global key never on a request
        assert json.loads(request.read()) == {"mediaType": "movie", "mediaId": 42}
        return httpx.Response(201, json={"id": 1, "media": {"status": 2}})

    code = await _media_client(handler).create_request("connect.sid=abc", "movie", 42)

    assert code == 2


async def test_create_request_tv_asks_for_all_seasons() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert json.loads(request.read()) == {"mediaType": "tv", "mediaId": 7, "seasons": "all"}
        return httpx.Response(201, json={"id": 2, "media": {"status": 3}})

    code = await _media_client(handler).create_request("connect.sid=abc", "tv", 7)

    assert code == 3


async def test_create_request_403_is_typed_rejection() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"status": 403, "error": "You do not have permission"})

    with pytest.raises(UpstreamRejected) as excinfo:
        await _media_client(handler).create_request("connect.sid=stale", "movie", 42)
    assert excinfo.value.status_code == 403


async def test_create_request_other_4xx_is_rejection() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"message": "bad request"})

    with pytest.raises(UpstreamRejected):
        await _media_client(handler).create_request("connect.sid=abc", "movie", 42)


async def test_create_request_5xx_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    with pytest.raises(UpstreamUnavailable):
        await _media_client(handler).create_request("connect.sid=abc", "movie", 42)


async def test_create_request_unparseable_body_defaults_pending() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(201, text="")  # accepted, but no JSON body

    code = await _media_client(handler).create_request("connect.sid=abc", "movie", 42)

    assert code == 2  # MEDIA_STATUS_PENDING


# ── SeerrClient: request history (global API key, cold-start seed) ───────────


def _history_row(
    tmdb_id: int, media_type: str = "movie", created: str = "2026-01-01"
) -> dict[str, object]:
    return {
        "id": tmdb_id,
        "createdAt": f"{created}T12:00:00.000Z",
        "media": {"tmdbId": tmdb_id, "mediaType": media_type},
        "requestedBy": {"id": 7},
    }


async def test_list_requests_walks_pages_with_the_filter() -> None:
    pages: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/request"
        assert request.headers["x-api-key"] == "seerr-api-key"
        assert "cookie" not in request.headers  # a read never carries a user cookie
        params = dict(request.url.params)
        pages.append(params)
        assert params["requestedBy"] == "7"
        skip = int(params["skip"])
        if skip == 0:
            rows = [_history_row(i) for i in range(50)]
        else:
            rows = [_history_row(100), _history_row(200, "tv")]
        return httpx.Response(200, json={"results": rows})

    history = await _media_client(handler).list_requests(7)

    assert len(pages) == 2  # a short second page ends the walk
    assert len(history) == 52
    assert history[-1].media_type == "tv"
    assert history[-1].tmdb_id == 200
    assert history[0].created_at.year == 2026


async def test_list_requests_is_capped() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        rows = [_history_row(int(dict(request.url.params)["skip"]) + i) for i in range(50)]
        return httpx.Response(200, json={"results": rows})

    history = await _media_client(handler).list_requests(7)

    assert len(history) == 200  # HISTORY_MAX_ROWS


async def test_list_requests_skips_malformed_rows() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        rows: list[dict[str, object]] = [
            _history_row(1),
            {"createdAt": "2026-01-01T12:00:00.000Z", "media": None},  # no media block
            {"createdAt": "2026-01-01T12:00:00.000Z", "media": {"mediaType": "movie"}},  # no id
            _history_row(2, media_type="music"),  # unknown type
            {"createdAt": "not a date", "media": {"tmdbId": 3, "mediaType": "movie"}},
            _history_row(4, media_type="tv"),
        ]
        return httpx.Response(200, json={"results": rows})

    history = await _media_client(handler).list_requests(7)

    assert [(h.media_type, h.tmdb_id) for h in history] == [("movie", 1), ("tv", 4)]


async def test_list_requests_bounded_by_raw_pages_not_parsed_rows() -> None:
    """A misbehaving upstream serving full pages of malformed rows must not
    extend the walk — the bound counts requests, not parseable rows."""
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        rows = [{"createdAt": "not a date", "media": {"mediaType": "book"}}] * 50
        return httpx.Response(200, json={"results": rows})

    history = await _media_client(handler).list_requests(7)

    assert history == []
    assert calls == 4  # HISTORY_MAX_ROWS / HISTORY_PAGE_SIZE, no further requests


async def test_list_requests_5xx_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    with pytest.raises(UpstreamUnavailable):
        await _media_client(handler).list_requests(7)

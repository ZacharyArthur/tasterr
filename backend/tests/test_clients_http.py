# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from tasterr.clients.http import TIMEOUT_SECONDS, create_http_client
from tasterr.clients.seerr import SeerrAuthClient
from tasterr.main import create_app
from tasterr.settings import Settings


def test_factory_sets_default_timeout() -> None:
    client = create_http_client()
    try:
        assert client.timeout == httpx.Timeout(TIMEOUT_SECONDS)
    finally:
        # aclose is async; the sync transport list is empty pre-use, so GC is fine here.
        pass


async def test_shared_client_never_replays_upstream_cookies() -> None:
    """Two users' logins on the one shared client: the second request must not
    carry the first login's connect.sid (cross-user session bleed)."""
    seen_cookie_headers: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_cookie_headers.append(request.headers.get("cookie"))
        return httpx.Response(
            200,
            json={"id": len(seen_cookie_headers), "permissions": 0},
            headers={"set-cookie": "connect.sid=s%3Aleaky; Path=/; HttpOnly"},
        )

    client = create_http_client(transport=httpx.MockTransport(handler))
    try:
        seerr = SeerrAuthClient(client, "http://seerr:5055")
        first = await seerr.login_local("a@b.c", "pw-a")
        second = await seerr.login_local("b@c.d", "pw-b")
    finally:
        await client.aclose()

    assert seen_cookie_headers == [None, None]
    # Extraction from each response still works with the jar disabled.
    assert first.cookie == second.cookie == "connect.sid=s%3Aleaky"


def test_lifespan_owns_the_shared_client(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"database_path": tmp_path / "tasterr.db", "static_dir": tmp_path / "static"}
    )
    app = create_app(settings)

    with TestClient(app):
        http = app.state.http
        assert isinstance(http, httpx.AsyncClient)
        assert not http.is_closed

    assert http.is_closed

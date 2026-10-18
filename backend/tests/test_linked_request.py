# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import asyncio
from pathlib import Path

import httpx
import pytest
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_request_api import (
    SEED_COOKIE,
    _app,
    _body,
    _client,
    _override_ctx,
    _seed_session,
    _stored_cookie,
)

from tasterr.api.destinations import get_destinations_client
from tasterr.api.request import SeerrRequestCtx, _request_with_reauth
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.deps import AuthedSession
from tasterr.auth.login import ProvenAccount, complete_login, get_link, link_account
from tasterr.auth.sessions import resolve_session
from tasterr.clients.plex import PlexCloudAccount
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient, SeerrLogin, SeerrUser
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import LinkedAccount, User


def test_no_seerr_link_never_calls_upstream(tmp_path: Path) -> None:
    path = tmp_path / "tasterr.db"
    token = _seed_session(path, plex_token="token")

    async def remove() -> None:
        engine = create_engine(path)
        async with async_sessionmaker(engine)() as db:
            await db.execute(delete(LinkedAccount).where(LinkedAccount.provider == "seerr"))
            await db.commit()
        await engine.dispose()

    asyncio.run(remove())

    def unexpected(_: httpx.Request) -> httpx.Response:
        raise AssertionError("No upstream call without a Seerr link")

    app = _app(tmp_path)
    _override_ctx(app, unexpected)
    app.dependency_overrides[get_destinations_client] = lambda: SeerrClient(
        httpx.AsyncClient(transport=httpx.MockTransport(unexpected)),
        "http://seerr",
        "key",
    )
    with _client(app, token) as client:
        assert client.post("/api/v1/request", json=_body()).json()["status"] == "re_auth_required"
        options = client.get("/api/v1/movie/42/destinations").json()
        assert options["available"] is False and options["destinations"] == []


def test_reauth_different_account_discards_cookie_and_never_retries(tmp_path: Path) -> None:
    path = tmp_path / "tasterr.db"
    token = _seed_session(path, plex_token="token")
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        if request.url.path == "/api/v1/auth/plex":
            return httpx.Response(
                200, json={"id": 555}, headers={"set-cookie": "connect.sid=other"}
            )
        calls += 1
        return httpx.Response(403)

    app = _app(tmp_path)
    _override_ctx(app, handler)
    with _client(app, token) as client:
        assert client.post("/api/v1/request", json=_body()).json()["status"] == "re_auth_required"
    assert calls == 1
    assert _stored_cookie(path, token) == SEED_COOKIE


@pytest.mark.parametrize("credential", [None, "unreadable-ciphertext"])
def test_missing_or_unreadable_cookie_never_calls_upstream(
    tmp_path: Path, credential: str | None
) -> None:
    path = tmp_path / "tasterr.db"
    token = _seed_session(path, plex_token="token")

    async def prepare() -> None:
        engine = create_engine(path)
        try:
            async with async_sessionmaker(engine)() as db:
                await db.execute(
                    update(LinkedAccount)
                    .where(LinkedAccount.provider == "seerr")
                    .values(credential_enc=credential)
                )
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(prepare())

    def unexpected(_request: httpx.Request) -> httpx.Response:
        raise AssertionError("Missing or unreadable Seerr credentials must not call upstream")

    app = _app(tmp_path)
    _override_ctx(app, unexpected)
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())
        assert response.status_code == 200 and response.json()["status"] == "re_auth_required"


@pytest.mark.parametrize("other_owner", [False, True])
async def test_late_reauth_cannot_refresh_or_retry_a_replacement_link(
    tmp_path: Path, other_owner: bool
) -> None:
    engine = create_engine(tmp_path / "reauth.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    started, release = asyncio.Event(), asyncio.Event()
    request_calls = 0
    secret = "reauth-test-secret"

    async def response(request: httpx.Request) -> httpx.Response:
        nonlocal request_calls
        if request.url.path == "/api/v1/auth/plex":
            started.set()
            await release.wait()
            return httpx.Response(
                200, json={"id": 7}, headers={"set-cookie": "connect.sid=late-cookie"}
            )
        request_calls += 1
        return httpx.Response(403)

    try:
        async with (
            maker() as db,
            httpx.AsyncClient(transport=httpx.MockTransport(response)) as http,
        ):
            user, token = await complete_login(
                db,
                secret,
                ProvenAccount.plex(PlexCloudAccount(id=8, username="member"), "plex-token"),
                SeerrLogin(SeerrUser(id=7), "connect.sid=original"),
                None,
            )
            resolved = await resolve_session(db, token)
            original = await get_link(db, user.id, "seerr")
            assert resolved is not None and original is not None
            ctx = SeerrRequestCtx(
                SeerrClient(http, "http://seerr", "key"),
                SeerrAuthClient(http, "http://seerr"),
                secret,
            )
            async with asyncio.timeout(5):
                task = asyncio.create_task(
                    _request_with_reauth(
                        ctx,
                        db,
                        AuthedSession(user, resolved.session),
                        "movie",
                        42,
                        seerr_link=original,
                        cookie="connect.sid=original",
                    )
                )
                await started.wait()
                async with maker() as other:
                    await other.execute(
                        delete(LinkedAccount).where(LinkedAccount.id == original.id)
                    )
                    if other_owner:
                        new_user = User(display_name="other member")
                        other.add(new_user)
                        await other.flush()
                        owner_id = new_user.id
                    else:
                        owner_id = user.id
                    replacement = await link_account(
                        other,
                        secret,
                        owner_id,
                        ProvenAccount(
                            "seerr", "99", "replacement", None, "connect.sid=replacement"
                        ),
                    )
                    assert replacement.id == original.id  # SQLite reuses the deleted highest id.
                    await other.commit()
                release.set()
                outcome = await task
            assert outcome.status == "re_auth_required"
            assert request_calls == 1
        async with maker() as observer:
            current = await get_link(observer, owner_id, "seerr")
            assert current is not None and current.credential_enc is not None
            assert current.external_id == "99"
            assert decrypt_token(secret, current.credential_enc) == "connect.sid=replacement"
    finally:
        release.set()
        await engine.dispose()

# starlette's TestClient ships partially-unknown method annotations; relax
# only the unknown-type rules rather than sprinkling casts.
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.auth import AuthContext, get_auth_context
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.plex import PlexAuthClient, PlexPin
from tasterr.clients.seerr import SeerrAuthClient, SeerrLogin, SeerrUser
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User, UserSession, utcnow
from tasterr.main import create_app
from tasterr.settings import Settings

SECRET = "test-secret-key"
PLEX_TOKEN = "plex-auth-token-sentinel"
SEERR_COOKIE = "connect.sid=s%3Aseerr-cookie-sentinel"


class FakePlex:
    """Same surface as PlexAuthClient; `token` simulates the user approving."""

    def __init__(self) -> None:
        self.pin = PlexPin(id=123456, code="abcd1234efgh")
        self.token: str | None = None
        self.expired = False
        self.delay = 0.0  # lets race tests widen the poll window

    async def create_pin(self) -> PlexPin:
        return self.pin

    async def poll_pin(self, pin_id: int) -> str | None:
        assert pin_id == self.pin.id
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.expired:
            raise UpstreamRejected(404)
        return self.token

    def auth_url(self, code: str) -> str:
        return f"https://app.plex.tv/auth#?clientID=test&code={code}"


class FakeSeerr:
    def __init__(self) -> None:
        self.user = SeerrUser.model_validate(
            {"id": 7, "displayName": "Viewer", "avatar": "https://a/b.png", "permissions": 2}
        )
        self.accepted = {("a@b.c", "hunter2-password-sentinel")}
        self.down = False
        self.login_calls = 0

    def _login(self) -> SeerrLogin:
        return SeerrLogin(user=self.user, cookie=SEERR_COOKIE)

    async def login_plex(self, auth_token: str) -> SeerrLogin:
        self.login_calls += 1
        if self.down:
            raise UpstreamUnavailable("seerr down")
        if auth_token != PLEX_TOKEN:
            raise UpstreamRejected(403)
        return self._login()

    async def login_local(self, email: str, password: str) -> SeerrLogin:
        self.login_calls += 1
        if self.down:
            raise UpstreamUnavailable("seerr down")
        if (email, password) not in self.accepted:
            raise UpstreamRejected(403)
        return self._login()


@dataclass
class Harness:
    app: FastAPI
    db_path: Path
    plex: FakePlex = field(default_factory=FakePlex)
    seerr: FakeSeerr = field(default_factory=FakeSeerr)
    pins: PinStore = field(default_factory=PinStore)


def _harness(tmp_path: Path, *, configured: bool = True, with_secret: bool = True) -> Harness:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
    }
    if configured:
        overrides |= {
            "seerr_internal_url": "http://seerr:5055",
            "seerr_api_key": "seerr-api-key",
        }
        if with_secret:
            overrides |= {"tasterr_secret_key": SECRET}
    harness = Harness(
        app=create_app(Settings.model_validate(overrides)), db_path=tmp_path / "tasterr.db"
    )
    if configured and with_secret:
        # Real get_auth_context still guards the unconfigured case (tested below).
        harness.app.dependency_overrides[get_auth_context] = lambda: AuthContext(
            secret_key=SECRET,
            plex=cast(PlexAuthClient, harness.plex),
            seerr=cast(SeerrAuthClient, harness.seerr),
            pins=harness.pins,
        )
    return harness


def _start_pin_login(client: TestClient) -> str:
    response = client.post("/api/v1/auth/plex/pin")
    assert response.status_code == 200
    return response.json()["pin_id"]


def _poll_pin(client: TestClient, handle: str, **headers: str) -> httpx.Response:
    """POST the same-origin-protected poll. `headers` carries fetch metadata or
    Origin for the CSRF regressions; the default (no headers) matches what
    Starlette's TestClient sends and is treated as a non-browser client by
    `require_same_origin`."""
    return client.post(
        "/api/v1/auth/plex/pin/poll", json={"pin_id": handle}, headers=headers or None
    )


# --- Plex PIN flow (4.2) ---


def test_create_pin_returns_opaque_handle_and_auth_url(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        response = client.post("/api/v1/auth/plex/pin")

    assert response.status_code == 200
    body = response.json()
    assert body["auth_url"].startswith("https://app.plex.tv/auth#?")
    assert body["pin_id"] != "123456"
    assert "123456" not in response.text  # raw plex.tv PIN id never leaves the server


def test_poll_pending_sets_no_cookie(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        response = _poll_pin(client, handle)

    assert response.status_code == 200
    assert response.json() == {"status": "pending", "user": None}
    assert "set-cookie" not in response.headers


def test_poll_after_approval_logs_in(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN

        response = _poll_pin(client, handle)

        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "ok"
        assert body["user"] == {
            "id": 1,
            "display_name": "Viewer",
            "avatar_url": "https://a/b.png",
            "is_admin": True,
        }
        assert "tasterr_session=" in response.headers["set-cookie"]
        assert PLEX_TOKEN not in response.text
        assert SEERR_COOKIE not in response.text

        me = client.get("/api/v1/auth/me")
        assert me.status_code == 200
        assert me.json()["display_name"] == "Viewer"


def test_handle_is_single_use_after_login(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        assert _poll_pin(client, handle).status_code == 200

        replay = _poll_pin(client, handle)

    assert replay.status_code == 404


def test_poll_unknown_handle_is_generic_404(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        response = _poll_pin(client, "no-such-handle")

    assert response.status_code == 404
    assert response.json() == {"detail": "Unknown or expired sign-in attempt"}


def test_poll_expired_plex_pin_is_404_and_consumed(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.expired = True

        first = _poll_pin(client, handle)
        harness.plex.expired = False
        second = _poll_pin(client, handle)

    assert first.status_code == 404
    assert second.status_code == 404  # consumed on expiry, not retryable


def test_seerr_rejecting_plex_account_is_generic_401(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = "some-token-seerr-refuses"

        response = _poll_pin(client, handle)

    assert response.status_code == 401
    assert response.json() == {"detail": "Sign-in failed"}


def test_plex_token_is_encrypted_at_rest(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        assert _poll_pin(client, handle).status_code == 200

    raw = harness.db_path.read_bytes()
    assert PLEX_TOKEN.encode() not in raw  # Fernet ciphertext only
    assert SEERR_COOKIE.encode() in raw  # stored verbatim per SPEC §5, server-side only


async def test_concurrent_claimed_polls_mint_exactly_one_session(tmp_path: Path) -> None:
    """Overlapping polls on a claimed PIN: one wins the handle, one gets the
    generic 404, and only a single session row exists afterwards."""
    harness = _harness(tmp_path)
    harness.plex.delay = 0.02  # both polls pass the peek before either can claim
    app = harness.app

    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as client:
            created = await client.post("/api/v1/auth/plex/pin")
            handle = created.json()["pin_id"]
            harness.plex.token = PLEX_TOKEN

            first, second = await asyncio.gather(
                client.post("/api/v1/auth/plex/pin/poll", json={"pin_id": handle}),
                client.post("/api/v1/auth/plex/pin/poll", json={"pin_id": handle}),
            )

    assert sorted([first.status_code, second.status_code]) == [200, 404]

    engine = create_engine(harness.db_path)
    try:
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            count = (await db.execute(select(func.count()).select_from(UserSession))).scalar_one()
    finally:
        await engine.dispose()
    assert count == 1


# --- Plex PIN poll: CSRF / session-swap hardening ---


def _session_count(db_path: Path) -> int:
    """Count UserSession rows directly in the SQLite file (race-free read)."""

    async def _run() -> int:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                stmt = select(func.count()).select_from(UserSession)
                return (await db.execute(stmt)).scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_cross_site_poll_is_rejected_before_any_side_effect(tmp_path: Path) -> None:
    """The CSRF fix: a cross-site poll must 403 before Plex/Seerr calls, handle
    consumption, cookie changes, or session creation."""
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN  # the attacker's approved PIN
        seerr_before = harness.seerr.login_calls

        response = _poll_pin(client, handle, **{"Sec-Fetch-Site": "cross-site"})
        seerr_during = harness.seerr.login_calls - seerr_before

        # The handle survives the rejection: a follow-up poll still answers
        # pending (the PIN returns no token once we clear the simulated approval,
        # so this proves the handle was NOT consumed without minting a session).
        harness.plex.token = None
        pending = _poll_pin(client, handle)

    assert response.status_code == 403
    assert seerr_during == 0  # no upstream login fired
    assert "set-cookie" not in response.headers  # no cookie touched
    assert pending.status_code == 200  # handle was NOT consumed
    assert pending.json() == {"status": "pending", "user": None}
    assert _session_count(harness.db_path) == 0  # no session minted


def test_victim_session_survives_a_rejected_cross_site_poll(tmp_path: Path) -> None:
    """A victim with an existing session must come out the other side of a
    cross-site poll attempt still identified as themselves, with no extra
    session row."""
    harness = _harness(tmp_path)
    victim_token = _seed_session_token(harness.db_path)  # display_name="Seeded"

    with TestClient(harness.app) as client:
        client.cookies.set("tasterr_session", victim_token)
        me_before = client.get("/api/v1/auth/me")
        assert me_before.status_code == 200
        assert me_before.json()["display_name"] == "Seeded"

        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN  # attacker's approved PIN
        rejected = _poll_pin(client, handle, **{"Sec-Fetch-Site": "cross-site"})

        # Same cookie value, same identity, after the attempt.
        assert client.cookies.get("tasterr_session") == victim_token
        me_after = client.get("/api/v1/auth/me")
        assert me_after.status_code == 200
        assert me_after.json()["display_name"] == "Seeded"

    assert rejected.status_code == 403
    assert _session_count(harness.db_path) == 1  # only the victim's row


def test_mismatched_origin_poll_is_rejected(tmp_path: Path) -> None:
    """The Origin fallback path: without fetch metadata, a cross-origin Origin
    is rejected 403 with no upstream call and no session minted."""
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        seerr_before = harness.seerr.login_calls

        response = _poll_pin(client, handle, **{"Origin": "https://evil.example"})

    assert response.status_code == 403
    assert harness.seerr.login_calls == seerr_before
    assert _session_count(harness.db_path) == 0


def test_same_origin_and_headerless_polls_still_complete_login(tmp_path: Path) -> None:
    """The guard's intentional behavior: same-origin fetch metadata passes, none
    passes (non-browser client — CSRF is a browser attack), same-site rejects."""
    harness = _harness(tmp_path)

    # same-origin completes.
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        same_origin = _poll_pin(client, handle, **{"Sec-Fetch-Site": "same-origin"})
        assert same_origin.status_code == 200
        assert same_origin.json()["status"] == "ok"
        assert "tasterr_session=" in same_origin.headers["set-cookie"]

    # none (user-initiated, e.g. typed address bar) completes.
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        none_site = _poll_pin(client, handle, **{"Sec-Fetch-Site": "none"})
        assert none_site.status_code == 200
        assert none_site.json()["status"] == "ok"

    # headerless non-browser client completes (the existing default behavior).
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        headerless = _poll_pin(client, handle)
        assert headerless.status_code == 200
        assert headerless.json()["status"] == "ok"

    # same-site is rejected (sibling origin to a registrable domain).
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        same_site = _poll_pin(client, handle, **{"Sec-Fetch-Site": "same-site"})
        assert same_site.status_code == 403
        assert "set-cookie" not in same_site.headers


def test_old_get_poll_route_cannot_mint_a_session(tmp_path: Path) -> None:
    """The removed GET completion route must not exist: a request to it 404s
    without any Seerr call, handle consumption, cookie change, or session row."""
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        seerr_before = harness.seerr.login_calls

        response = client.get(f"/api/v1/auth/plex/pin/{handle}")
        seerr_during_get = harness.seerr.login_calls - seerr_before

        # The handle survives the 404: a follow-up poll still answers pending.
        harness.plex.token = None
        pending = _poll_pin(client, handle)

    assert response.status_code == 404  # no such route
    assert seerr_during_get == 0
    assert "set-cookie" not in response.headers
    assert pending.json() == {"status": "pending", "user": None}
    assert _session_count(harness.db_path) == 0


# --- Local login (4.3) ---


def test_local_login_mints_session(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        response = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )

        assert response.status_code == 200
        assert response.json()["display_name"] == "Viewer"
        assert "tasterr_session=" in response.headers["set-cookie"]
        assert SEERR_COOKIE not in response.text
        assert "connect.sid" not in response.headers.get("set-cookie", "")
        assert client.get("/api/v1/auth/me").status_code == 200


def test_local_login_failures_are_indistinguishable(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        wrong_password = client.post(
            "/api/v1/auth/local", json={"email": "a@b.c", "password": "wrong"}
        )
        unknown_account = client.post(
            "/api/v1/auth/local", json={"email": "nobody@b.c", "password": "wrong"}
        )

    assert wrong_password.status_code == unknown_account.status_code == 401
    assert (
        wrong_password.json() == unknown_account.json() == {"detail": "Invalid email or password"}
    )


def test_credentials_never_persisted_or_logged(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    harness = _harness(tmp_path)
    with caplog.at_level("DEBUG"), TestClient(harness.app) as client:
        client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )

    assert "hunter2-password-sentinel" not in caplog.text
    assert b"hunter2-password-sentinel" not in harness.db_path.read_bytes()


# --- User upsert + admin derivation (4.4) ---


def test_repeat_login_updates_user_in_place(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        first = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        assert first.json() == {
            "id": 1,
            "display_name": "Viewer",
            "avatar_url": "https://a/b.png",
            "is_admin": True,
        }

        harness.seerr.user.display_name = "Renamed"
        harness.seerr.user.permissions = 0  # admin revoked in Seerr

        second = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )

    assert second.json() == {
        "id": 1,  # same row, not a duplicate
        "display_name": "Renamed",
        "avatar_url": "https://a/b.png",
        "is_admin": False,
    }


def test_admin_requires_permission_bit_two(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.seerr.user.permissions = 4  # some other permission bit
    with TestClient(harness.app) as client:
        response = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )

    assert response.json()["is_admin"] is False


def _read_last_login(db_path: Path) -> datetime:
    async def _run() -> datetime:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                return (await db.execute(select(User.last_login_at))).scalar_one()
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_repeat_login_refreshes_last_login_at(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = {"email": "a@b.c", "password": "hunter2-password-sentinel"}
    with TestClient(harness.app) as client:
        client.post("/api/v1/auth/local", json=payload)
        first = _read_last_login(harness.db_path)
        client.post("/api/v1/auth/local", json=payload)
        second = _read_last_login(harness.db_path)

    assert second > first


def test_relogin_with_existing_cookie_rotates_the_token(tmp_path: Path) -> None:
    """No fixation: presenting a live session cookie at login still mints fresh."""
    harness = _harness(tmp_path)
    payload = {"email": "a@b.c", "password": "hunter2-password-sentinel"}
    with TestClient(harness.app) as client:
        client.post("/api/v1/auth/local", json=payload)
        first = client.cookies.get("tasterr_session")
        client.post("/api/v1/auth/local", json=payload)  # old cookie rides along
        second = client.cookies.get("tasterr_session")

    assert first is not None and second is not None
    assert first != second


# --- Me + logout (4.5) ---


def test_me_without_session_is_401(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        assert client.get("/api/v1/auth/me").status_code == 401


def test_me_makes_no_seerr_calls(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        calls_after_login = harness.seerr.login_calls

        for _ in range(3):
            assert client.get("/api/v1/auth/me").status_code == 200

    assert harness.seerr.login_calls == calls_after_login


def test_logout_revokes_server_side(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        session_cookie = client.cookies.get("tasterr_session")
        assert session_cookie is not None

        logout = client.post("/api/v1/auth/logout")
        assert logout.status_code == 204
        assert "max-age=0" in logout.headers["set-cookie"].lower()

        # Replaying the revoked cookie must fail server-side.
        client.cookies.set("tasterr_session", session_cookie)
        assert client.get("/api/v1/auth/me").status_code == 401


def test_rate_limited_logout_preserves_session_and_cookie(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        login = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        assert login.status_code == 200
        session_cookie = client.cookies.get("tasterr_session")
        assert session_cookie is not None
        harness.app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)

        rejected = client.post("/api/v1/auth/logout")
        still_authed = client.get("/api/v1/auth/me")

    assert rejected.status_code == 429
    assert rejected.json() == {"detail": "Too many actions"}
    assert "max-age=0" not in rejected.headers.get("set-cookie", "").lower()
    assert client.cookies.get("tasterr_session") == session_cookie
    assert still_authed.status_code == 200


# --- Unconfigured / degraded (4.6) ---


def test_unconfigured_auth_returns_generic_503(tmp_path: Path) -> None:
    harness = _harness(tmp_path, configured=False)
    with TestClient(harness.app) as client:
        pin = client.post("/api/v1/auth/plex/pin")
        local = client.post("/api/v1/auth/local", json={"email": "a", "password": "b"})
        health = client.get("/api/v1/health")

    assert pin.status_code == local.status_code == 503
    assert pin.json() == {"detail": "Authentication unavailable"}
    assert health.status_code == 200


def test_missing_secret_key_alone_disables_auth(tmp_path: Path) -> None:
    harness = _harness(tmp_path, with_secret=False)  # Seerr configured, key absent
    with TestClient(harness.app) as client:
        response = client.post("/api/v1/auth/local", json={"email": "a@b.c", "password": "x"})

    assert response.status_code == 503
    assert response.json() == {"detail": "Authentication unavailable"}


def _seed_session_token(db_path: Path, *, stale: bool = False) -> str:
    async def _run() -> str:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(
                    seerr_user_id=99,
                    display_name="Seeded",
                    avatar_url=None,
                    auth_type="local",
                    is_admin=False,
                )
                db.add(user)
                await db.flush()
                token = await mint_session(db, user.id, "connect.sid=s%3Aseed", None)
                if stale:
                    row = (await db.execute(select(UserSession))).scalar_one()
                    row.last_seen_at = utcnow() - timedelta(hours=2)
                    await db.commit()
                return token
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_stale_logout_clears_with_a_single_cookie_header(tmp_path: Path) -> None:
    """Logout's deletion must be the only Set-Cookie — never paired with a
    sliding refresh for the same name (RFC 6265: duplicate names are
    unreliable client-side)."""
    harness = _harness(tmp_path)
    token = _seed_session_token(harness.db_path, stale=True)

    with TestClient(harness.app) as client:
        client.cookies.set("tasterr_session", token)
        response = client.post("/api/v1/auth/logout")

    assert response.status_code == 204
    cookie_headers: list[str] = response.headers.get_list("set-cookie")
    assert len(cookie_headers) == 1
    assert "max-age=0" in cookie_headers[0].lower()


def test_me_and_logout_still_work_while_auth_unconfigured(tmp_path: Path) -> None:
    """Degradation contract: existing sessions outlive a lost Seerr config."""
    harness = _harness(tmp_path, configured=False)
    token = _seed_session_token(harness.db_path)
    with TestClient(harness.app) as client:
        client.cookies.set("tasterr_session", token)
        assert client.get("/api/v1/auth/me").status_code == 200
        assert client.post("/api/v1/auth/logout").status_code == 204


def test_seerr_down_is_generic_502_and_health_still_up(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    harness.seerr.down = True
    with TestClient(harness.app) as client:
        response = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        health = client.get("/api/v1/health")

    assert response.status_code == 502
    assert response.json() == {"detail": "Sign-in service unavailable"}
    assert "seerr" not in response.text.lower() or "Sign-in" in response.text
    assert health.status_code == 200


# --- Session-gated /config (4.7) ---


def test_config_requires_session(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        assert client.get("/api/v1/config").status_code == 401


def test_config_serves_public_projection_without_secrets(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        response = client.get("/api/v1/config")

    assert response.status_code == 200
    assert response.json() == {
        "tmdb_configured": False,
        "seerr_configured": True,
        "appearance": {"theme": "dark", "accent": "crimson"},
    }
    assert SECRET not in response.text
    assert "seerr:5055" not in response.text


# --- Hardening wiring (4.8) ---


def test_cross_origin_login_rejected_before_seerr_call(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        response = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
            headers={"Sec-Fetch-Site": "cross-site"},
        )

    assert response.status_code == 403
    assert harness.seerr.login_calls == 0


def test_login_burst_hits_rate_limit(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        statuses = [
            client.post(
                "/api/v1/auth/local", json={"email": "a@b.c", "password": "wrong"}
            ).status_code
            for _ in range(12)
        ]

    assert statuses[:10] == [401] * 10
    assert statuses[10:] == [429, 429]


def test_pin_polling_is_exempt_from_login_bucket(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        handle = _start_pin_login(client)
        statuses = {_poll_pin(client, handle).status_code for _ in range(25)}

    assert statuses == {200}


def test_session_cookie_secure_follows_scheme(tmp_path: Path) -> None:
    harness = _harness(tmp_path)
    payload = {"email": "a@b.c", "password": "hunter2-password-sentinel"}

    with TestClient(harness.app, base_url="http://testserver") as client:
        plain = client.post("/api/v1/auth/local", json=payload)
    with TestClient(harness.app, base_url="https://testserver") as client:
        secure = client.post("/api/v1/auth/local", json=payload)

    assert "secure" not in plain.headers["set-cookie"].lower()
    assert "secure" in secure.headers["set-cookie"].lower()


# --- Cold-start seed hook (M4) ---


def test_logins_schedule_the_cold_start_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both login paths hand the user off to the seed scheduler after the
    response is assembled — the login itself never waits on (or fails with)
    the import, which is unit-tested in test_recommend_seed.py."""
    scheduled: list[tuple[int, int]] = []

    def recorder(request: object, settings: object, user_id: int, seerr_user_id: int) -> None:
        scheduled.append((user_id, seerr_user_id))

    monkeypatch.setattr("tasterr.api.auth.schedule_seed", recorder)
    harness = _harness(tmp_path)
    with TestClient(harness.app) as client:
        local = client.post(
            "/api/v1/auth/local",
            json={"email": "a@b.c", "password": "hunter2-password-sentinel"},
        )
        handle = _start_pin_login(client)
        harness.plex.token = PLEX_TOKEN
        plex = _poll_pin(client, handle)

    assert local.status_code == 200
    assert plex.status_code == 200
    assert scheduled == [(1, 7), (1, 7)]  # same Seerr user -> same Tasterr user row

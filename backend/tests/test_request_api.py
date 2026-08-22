# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.api.request import SeerrRequestCtx, get_seerr_request_ctx
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import hash_token, mint_session
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Signal, User, UserSession
from tasterr.main import create_app
from tasterr.settings import Settings

SECRET = "test-secret-key"
SEERR_URL = "http://seerr:5055"
SEED_COOKIE = "connect.sid=s%3Aseed"
NEW_COOKIE = "connect.sid=fresh"
PLEX_USER = {"id": 1, "displayName": "Viewer", "permissions": 2}


def _app(
    tmp_path: Path, *, seerr: bool = True, external: str | None = "https://requests.example"
) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": SECRET,
    }
    if seerr:
        overrides["seerr_internal_url"] = SEERR_URL
        overrides["seerr_api_key"] = "seerr-api-key"
    if external is not None:
        overrides["seerr_external_url"] = external
    return create_app(Settings.model_validate(overrides))


def _seed_session(db_path: Path, *, plex_token: str | None = None) -> str:
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
                    auth_type="plex" if plex_token else "local",
                    is_admin=False,
                )
                db.add(user)
                await db.flush()
                enc = encrypt_token(SECRET, plex_token) if plex_token else None
                return await mint_session(db, user.id, SEED_COOKIE, enc)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _stored_cookie(db_path: Path, token: str) -> str:
    async def _run() -> str:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                row = (
                    await db.execute(
                        select(UserSession).where(UserSession.token_hash == hash_token(token))
                    )
                ).scalar_one()
                return row.seerr_cookie
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _override_ctx(app: FastAPI, handler: Callable[[httpx.Request], httpx.Response]) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    ctx = SeerrRequestCtx(
        client=SeerrClient(http, SEERR_URL, "seerr-api-key"),
        seerr_auth=SeerrAuthClient(http, SEERR_URL),
        secret_key=SECRET,
    )
    app.dependency_overrides[get_seerr_request_ctx] = lambda: ctx


def _client(app: FastAPI, token: str) -> TestClient:
    client = TestClient(app)
    client.cookies.set("tasterr_session", token)
    return client


def _body(media_type: str = "movie", tmdb_id: int = 42) -> dict[str, object]:
    return {"media_type": media_type, "tmdb_id": tmdb_id}


# ── Gating (session + CSRF) ──────────────────────────────────────────────────


def test_request_requires_a_session(tmp_path: Path) -> None:
    app = _app(tmp_path)
    with TestClient(app) as client:
        assert client.post("/api/v1/request", json=_body()).status_code == 401


def test_cross_origin_request_is_rejected(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(201, json={})

    app = _app(tmp_path)
    _override_ctx(app, handler)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/request", json=_body(), headers={"sec-fetch-site": "cross-site"}
        )

    assert response.status_code == 403
    assert calls == []  # rejected before any Seerr call


def test_out_of_range_request_is_rejected_before_upstream_or_taste_write(
    tmp_path: Path,
) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(201, json={"media": {"status": 2}})

    app = _app(tmp_path)
    _override_ctx(app, handler)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path)
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body(tmdb_id=2_147_483_648))

    assert response.status_code == 422
    assert calls == []
    assert _stored_taste_signals(db_path) == []


def test_rate_limited_request_has_no_upstream_or_taste_side_effect(tmp_path: Path) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        return httpx.Response(201, json={"media": {"status": 2}})

    app = _app(tmp_path)
    _override_ctx(app, handler)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex_token="plex-token")
    app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)

    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 429
    assert response.json() == {"detail": "Too many actions"}
    assert calls == []
    assert _stored_cookie(db_path, token) == SEED_COOKIE
    assert _stored_taste_signals(db_path) == []


# ── Success + attribution ────────────────────────────────────────────────────


def test_successful_request_returns_status_and_fallback(tmp_path: Path) -> None:
    seen: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v1/request"
        seen.append(request.headers.get("cookie"))
        assert json.loads(request.read()) == {"mediaType": "movie", "mediaId": 42}
        return httpx.Response(201, json={"id": 1, "media": {"status": 2}})

    app = _app(tmp_path)
    _override_ctx(app, handler)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "availability": {"status": "pending", "known": True, "playback": None},
        "seerr_url": "https://requests.example/movie/42",
    }
    assert seen == [SEED_COOKIE]  # attributed via the member's own cookie


def test_no_external_url_means_no_link(tmp_path: Path) -> None:
    app = _app(tmp_path, external=None)
    _override_ctx(app, lambda _: httpx.Response(201, json={"media": {"status": 2}}))
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    body = response.json()
    assert body["status"] == "ok"
    assert body["seerr_url"] is None
    assert SEERR_URL not in response.text  # internal URL never leaks


# ── The 403 re-auth ladder ───────────────────────────────────────────────────


@dataclass
class _LadderState:
    request_cookies: list[str | None] = field(default_factory=list)
    request_bodies: list[dict[str, object]] = field(default_factory=list)
    auth_plex_called: bool = False


def _ladder_handler(
    retry: httpx.Response,
) -> tuple[Callable[[httpx.Request], httpx.Response], _LadderState]:
    state = _LadderState()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/v1/request":
            state.request_cookies.append(request.headers.get("cookie"))
            state.request_bodies.append(json.loads(request.read()))
            if len(state.request_cookies) == 1:
                return httpx.Response(403, json={"status": 403, "error": "no permission"})
            return retry
        if request.url.path == "/api/v1/auth/plex":
            state.auth_plex_called = True
            assert json.loads(request.read()) == {"authToken": "plex-token"}
            return httpx.Response(
                200, json=PLEX_USER, headers={"set-cookie": f"{NEW_COOKIE}; Path=/; HttpOnly"}
            )
        raise AssertionError(f"unexpected path {request.url.path}")

    return handler, state


def test_plex_member_reauths_and_retries(tmp_path: Path) -> None:
    handler, state = _ladder_handler(httpx.Response(201, json={"media": {"status": 2}}))
    app = _app(tmp_path)
    _override_ctx(app, handler)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex_token="plex-token")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert state.request_cookies == [SEED_COOKIE, NEW_COOKIE]  # retried with the fresh cookie
    assert state.auth_plex_called is True
    assert _stored_cookie(db_path, token) == NEW_COOKIE  # refreshed cookie persisted


def test_persistent_denial_after_reauth_is_failed(tmp_path: Path) -> None:
    handler, state = _ladder_handler(httpx.Response(403, json={"status": 403, "error": "quota"}))
    app = _app(tmp_path)
    _override_ctx(app, handler)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path, plex_token="plex-token")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["seerr_url"] == "https://requests.example/movie/42"  # fallback still offered
    assert len(state.request_cookies) == 2  # exactly one re-auth + retry, no loop


def test_tv_denial_after_reauth_preserves_series_shape_without_looping(tmp_path: Path) -> None:
    # The ladder is media-type-agnostic: a TV request that 403s re-auths once and
    # retries with the whole-series body, and a second 403 is a generic failure —
    # no loop, no shape drift on the retry.
    handler, state = _ladder_handler(httpx.Response(403, json={"status": 403, "error": "quota"}))
    app = _app(tmp_path)
    _override_ctx(app, handler)
    token = _seed_session(tmp_path / "tasterr.db", plex_token="plex-token")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body("tv", 7))

    assert response.json()["status"] == "failed"
    assert len(state.request_cookies) == 2  # one re-auth + retry, no loop
    assert state.request_bodies == [
        {"mediaType": "tv", "mediaId": 7, "seasons": "all"},
        {"mediaType": "tv", "mediaId": 7, "seasons": "all"},  # series shape preserved on retry
    ]


def test_local_member_gets_re_auth_required(tmp_path: Path) -> None:
    handler, state = _ladder_handler(httpx.Response(201, json={"media": {"status": 2}}))
    app = _app(tmp_path)
    _override_ctx(app, handler)
    token = _seed_session(tmp_path / "tasterr.db")  # no stored Plex token
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    assert response.json()["status"] == "re_auth_required"
    assert state.auth_plex_called is False  # no silent re-auth for a local member


# ── Degradation ──────────────────────────────────────────────────────────────


def test_unconfigured_seerr_is_unavailable_without_a_call(tmp_path: Path) -> None:
    # Real dependency (no override): unconfigured → None ctx → "unavailable", no call.
    app = _app(tmp_path, seerr=False, external=None)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    assert response.json()["status"] == "unavailable"


def test_seerr_down_is_failed_with_fallback_and_browsing_survives(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _override_ctx(app, lambda _: httpx.Response(500, text="down"))
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())
        health = client.get("/api/v1/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "failed"
    assert body["seerr_url"] == "https://requests.example/movie/42"
    assert "down" not in response.text  # no upstream detail leaks
    assert health.status_code == 200  # browsing unaffected by a Seerr outage


# ── The server-side taste signal (M4) ────────────────────────────────────────


def _stored_taste_signals(db_path: Path) -> list[tuple[str, int, str]]:
    async def _run() -> list[tuple[str, int, str]]:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                rows = (await db.execute(select(Signal))).scalars().all()
                return [(r.media_type, r.tmdb_id, r.kind) for r in rows]
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def test_successful_request_records_a_taste_signal(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _override_ctx(app, lambda _: httpx.Response(201, json={"media": {"status": 2}}))
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.json()["status"] == "ok"
    assert _stored_taste_signals(tmp_path / "tasterr.db") == [("movie", 42, "request")]


def test_failed_request_records_no_signal(tmp_path: Path) -> None:
    app = _app(tmp_path)
    _override_ctx(app, lambda _: httpx.Response(500, text="down"))
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        client.post("/api/v1/request", json=_body())

    assert _stored_taste_signals(tmp_path / "tasterr.db") == []


def test_signal_write_failure_never_fails_the_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def boom(*_args: object, **_kwargs: object) -> bool:
        raise RuntimeError("signals table on fire")

    monkeypatch.setattr("tasterr.api.request.store.record_signal", boom)
    app = _app(tmp_path)
    _override_ctx(app, lambda _: httpx.Response(201, json={"media": {"status": 2}}))
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/request", json=_body())

    assert response.status_code == 200
    assert response.json()["status"] == "ok"  # Seerr accepted; the signal is best-effort
    assert _stored_taste_signals(tmp_path / "tasterr.db") == []

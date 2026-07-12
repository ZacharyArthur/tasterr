# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.auth.sessions import mint_session
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.main import create_app
from tasterr.recommend import store
from tasterr.recommend.features import FeatureRecord
from tasterr.settings import Settings

SEERR_USER_ID = 7

TMDB_DETAIL = {
    "id": 42,
    "title": "Deep",
    "genres": [{"id": 18, "name": "Drama"}],
    "vote_average": 8.0,
    "vote_count": 5000,
    "keywords": {"keywords": [{"id": 1, "name": "heist"}]},
}
HISTORY_PAGE = {
    "results": [
        {
            "createdAt": "2026-01-01T12:00:00.000Z",
            "media": {"tmdbId": 42, "mediaType": "movie"},
        },
        {
            "createdAt": "2025-06-01T12:00:00.000Z",
            "media": {"tmdbId": 1399, "mediaType": "tv"},
        },
    ]
}


def _app(tmp_path: Path, *, seerr: bool = True) -> FastAPI:
    overrides: dict[str, object] = {
        "database_path": tmp_path / "tasterr.db",
        "static_dir": tmp_path / "static",
        "tasterr_secret_key": "test-secret-key",
        "tmdb_api_key": "tmdb-key",
    }
    if seerr:
        overrides |= {
            "seerr_internal_url": "http://seerr:5055",
            "seerr_api_key": "seerr-api-key",
        }
    return create_app(Settings.model_validate(overrides))


def _run_db(db_path: Path, action: Callable[[AsyncSession], Awaitable[None]]) -> None:
    async def _go() -> None:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                await action(db)
                await db.commit()
        finally:
            await engine.dispose()

    asyncio.run(_go())


def _seed_session(db_path: Path, seerr_user_id: int = SEERR_USER_ID) -> tuple[str, int]:
    token_and_id: list[tuple[str, int]] = []

    async def _go() -> None:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(seerr_user_id=seerr_user_id, display_name="member", auth_type="local")
                db.add(user)
                await db.flush()
                token = await mint_session(db, user.id, "connect.sid=s%3Aseed", None)
                token_and_id.append((token, user.id))
        finally:
            await engine.dispose()

    asyncio.run(_go())
    return token_and_id[0]


def _client(app: FastAPI, token: str | None = None) -> TestClient:
    client = TestClient(app)
    if token is not None:
        client.cookies.set("tasterr_session", token)
    return client


def _mock_http(seerr_down: bool = False) -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.themoviedb.org":
            return httpx.Response(200, json=TMDB_DETAIL)
        if seerr_down:
            return httpx.Response(500, text="seerr boom")
        assert request.url.path == "/api/v1/request"
        assert request.headers["x-api-key"] == "seerr-api-key"
        return httpx.Response(200, json=HISTORY_PAGE)

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


# ── Explain ──────────────────────────────────────────────────────────────────


def test_explain_requires_a_session(tmp_path: Path) -> None:
    with _client(_app(tmp_path)) as client:
        response = client.get("/api/v1/recommendations/explain?type=movie&id=42")

    assert response.status_code == 401


def test_explain_validates_type_and_id(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        assert client.get("/api/v1/recommendations/explain?type=music&id=42").status_code == 422
        assert client.get("/api/v1/recommendations/explain?type=movie&id=0").status_code == 422


def test_explain_returns_reasons_for_a_profiled_user(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, user_id = _seed_session(tmp_path / "tasterr.db")

    async def prepare(db: AsyncSession) -> None:
        # A fresh profile + a fresh title vector: explain is pure arithmetic,
        # no TMDB call needed.
        await store.save_profile(db, user_id, {"genre:drama": 0.9, "kw:heist": 0.4})
        record = FeatureRecord(
            vector={"genre:drama": 0.8, "kw:heist": 0.6}, vote_average=8.0, vote_count=5000
        )
        await store.save_features(db, ("movie", 42), record)

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        response = client.get("/api/v1/recommendations/explain?type=movie&id=42")

    assert response.status_code == 200
    assert response.json() == {"personalized": True, "reasons": ["Drama", "heist"]}


def test_explain_is_honest_for_a_signalless_user(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.get("/api/v1/recommendations/explain?type=movie&id=42")

    assert response.status_code == 200
    assert response.json() == {"personalized": False, "reasons": []}


# ── Reset ────────────────────────────────────────────────────────────────────


def test_reset_requires_same_origin(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/reset", headers={"origin": "https://evil.example"}
        )

    assert response.status_code == 403


def test_reset_wipes_and_reseeds_from_history(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, user_id = _seed_session(tmp_path / "tasterr.db")

    async def prepare(db: AsyncSession) -> None:
        await store.record_signal(db, user_id, "movie", 99, "watchlist")
        await store.save_profile(db, user_id, {"genre:sentinel": 1.0})

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        app.state.http = _mock_http()
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 200
    assert response.json() == {"seeded_signals": 2}

    async def verify(db: AsyncSession) -> None:
        signals = await store.load_signals(db, user_id)
        assert {(s.media_type, s.tmdb_id, s.kind) for s in signals} == {
            ("movie", 42, "seed_request_history"),
            ("tv", 1399, "seed_request_history"),
        }
        profile = await store.load_profile(db, user_id)
        assert profile is not None
        assert "genre:sentinel" not in profile.vector  # rebuilt, not the old one

    _run_db(tmp_path / "tasterr.db", verify)


def test_reset_touches_only_the_caller(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    other_id: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        other = User(seerr_user_id=8, display_name="other", auth_type="local")
        db.add(other)
        await db.flush()
        other_id.append(other.id)
        await store.record_signal(db, other.id, "movie", 1, "watchlist")

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        app.state.http = _mock_http()
        assert client.post("/api/v1/recommendations/reset").status_code == 200

    async def verify(db: AsyncSession) -> None:
        assert await store.has_signals(db, other_id[0]) is True

    _run_db(tmp_path / "tasterr.db", verify)


def test_reset_with_seerr_down_still_clears(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, user_id = _seed_session(tmp_path / "tasterr.db")

    async def prepare(db: AsyncSession) -> None:
        await store.record_signal(db, user_id, "movie", 99, "watchlist")

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        app.state.http = _mock_http(seerr_down=True)
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 200
    assert response.json() == {"seeded_signals": 0}
    assert "boom" not in response.text  # no upstream detail leaks

    async def verify(db: AsyncSession) -> None:
        assert await store.has_signals(db, user_id) is False

    _run_db(tmp_path / "tasterr.db", verify)

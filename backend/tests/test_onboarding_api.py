# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false

import asyncio
from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

import tasterr.api.onboarding as onboarding_api
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Signal, User
from tasterr.main import create_app
from tasterr.settings import Settings


def _app(tmp_path: Path) -> FastAPI:
    settings = Settings.model_validate(
        {"database_path": tmp_path / "tasterr.db", "static_dir": tmp_path / "static"}
    )
    return create_app(settings)


def _seed_session(db_path: Path) -> tuple[str, int]:
    async def _run() -> tuple[str, int]:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(seerr_user_id=99, display_name="Member", auth_type="local")
                db.add(user)
                await db.flush()
                token = await mint_session(db, user.id, "connect.sid=seed", None)
                return token, user.id
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _stored_state(db_path: Path) -> tuple[bool, set[tuple[str, int, str]]]:
    async def _run() -> tuple[bool, set[tuple[str, int, str]]]:
        engine = create_engine(db_path)
        try:
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = (await db.execute(select(User))).scalars().one()
                signals = (await db.execute(select(Signal))).scalars().all()
                return user.taste_onboarding_seen, {
                    (row.media_type, row.tmdb_id, row.kind) for row in signals
                }
        finally:
            await engine.dispose()

    return asyncio.run(_run())


@pytest.fixture
def authed_client(tmp_path: Path) -> Generator[tuple[TestClient, FastAPI, Path, int]]:
    db_path = tmp_path / "tasterr.db"
    app = _app(tmp_path)
    token, user_id = _seed_session(db_path)
    with TestClient(app) as client:
        client.cookies.set("tasterr_session", token)
        yield client, app, db_path, user_id


def test_state_requires_authentication(tmp_path: Path) -> None:
    with TestClient(_app(tmp_path)) as client:
        response = client.get("/api/v1/taste-onboarding")
    assert response.status_code == 401


def test_empty_user_waits_for_seed_then_sees_picker(
    authed_client: tuple[TestClient, FastAPI, Path, int],
) -> None:
    client, app, _db_path, user_id = authed_client
    app.state.seeding.add(user_id)
    assert client.get("/api/v1/taste-onboarding").json() == {"state": "pending"}

    app.state.seeding.discard(user_id)
    assert client.get("/api/v1/taste-onboarding").json() == {"state": "show"}


def test_selections_are_idempotent_watchlist_signals_with_one_refresh_per_submit(
    authed_client: tuple[TestClient, FastAPI, Path, int],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client, _app_instance, db_path, user_id = authed_client
    refreshes: list[int] = []

    async def refresh(*args: object) -> None:
        refreshes.append(user_id)

    monkeypatch.setattr(onboarding_api, "refresh_profile", refresh)
    body = {
        "selections": [
            {"media_type": "movie", "tmdb_id": 42},
            {"media_type": "movie", "tmdb_id": 42},
            {"media_type": "tv", "tmdb_id": 7},
        ]
    }
    response = client.post("/api/v1/taste-onboarding", json=body)
    repeated = client.post("/api/v1/taste-onboarding", json=body)

    assert response.status_code == 200
    assert response.json() == {"recorded_signals": 2}
    assert repeated.json() == {"recorded_signals": 0}
    assert "tmdb_id" not in response.text
    assert refreshes == [user_id, user_id]
    assert _stored_state(db_path) == (
        True,
        {("movie", 42, "watchlist"), ("tv", 7, "watchlist")},
    )
    assert client.get("/api/v1/taste-onboarding").json() == {"state": "done"}


def test_existing_signal_suppresses_picker_even_while_seed_is_reserved(
    authed_client: tuple[TestClient, FastAPI, Path, int],
) -> None:
    client, app, _db_path, user_id = authed_client
    response = client.post(
        "/api/v1/signals",
        json={"media_type": "movie", "tmdb_id": 42, "kind": "detail_open"},
    )
    assert response.status_code == 200
    app.state.seeding.add(user_id)
    assert client.get("/api/v1/taste-onboarding").json() == {"state": "done"}


def test_skip_is_durable_across_taste_reset(
    authed_client: tuple[TestClient, FastAPI, Path, int],
) -> None:
    client, _app_instance, db_path, _user_id = authed_client
    skipped = client.post("/api/v1/taste-onboarding", json={"selections": []})
    assert skipped.json() == {"recorded_signals": 0}
    assert _stored_state(db_path) == (True, set())

    reset = client.post("/api/v1/recommendations/reset")
    assert reset.status_code == 200
    assert client.get("/api/v1/taste-onboarding").json() == {"state": "done"}


@pytest.mark.parametrize(
    "body",
    [
        {"selections": [{"media_type": "music", "tmdb_id": 1}]},
        {"selections": [{"media_type": "movie", "tmdb_id": 0}]},
        {"selections": [{"media_type": "movie", "tmdb_id": 2_147_483_648}]},
        {"selections": [{"media_type": "movie", "tmdb_id": tmdb_id} for tmdb_id in range(1, 14)]},
    ],
)
def test_invalid_selection_is_rejected(
    authed_client: tuple[TestClient, FastAPI, Path, int], body: dict[str, object]
) -> None:
    client, _app_instance, db_path, _user_id = authed_client
    assert client.post("/api/v1/taste-onboarding", json=body).status_code == 422
    assert _stored_state(db_path) == (False, set())


def test_cross_origin_and_rate_limited_completions_have_no_side_effect(
    authed_client: tuple[TestClient, FastAPI, Path, int],
) -> None:
    client, app, db_path, _user_id = authed_client
    body = {"selections": [{"media_type": "movie", "tmdb_id": 42}]}
    cross_origin = client.post(
        "/api/v1/taste-onboarding",
        json=body,
        headers={"origin": "https://evil.example"},
    )
    assert cross_origin.status_code == 403

    app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)
    limited = client.post("/api/v1/taste-onboarding", json=body)
    assert limited.status_code == 429
    assert _stored_state(db_path) == (False, set())

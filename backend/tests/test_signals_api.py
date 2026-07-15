# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import Signal, User
from tasterr.main import create_app
from tasterr.settings import Settings


def _app(tmp_path: Path) -> FastAPI:
    # TMDB deliberately unconfigured: signal writes must not depend on the
    # catalog; the profile refresh silently skips.
    settings = Settings.model_validate(
        {"database_path": tmp_path / "tasterr.db", "static_dir": tmp_path / "static"}
    )
    return create_app(settings)


def _seed_session(db_path: Path) -> str:
    async def _run() -> str:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(seerr_user_id=99, display_name="Seeded", auth_type="local")
                db.add(user)
                await db.flush()
                return await mint_session(db, user.id, "connect.sid=s%3Aseed", None)
        finally:
            await engine.dispose()

    return asyncio.run(_run())


def _stored_signals(db_path: Path) -> list[tuple[str, int, str]]:
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


def _client(app: FastAPI, token: str | None = None) -> TestClient:
    client = TestClient(app)
    if token is not None:
        client.cookies.set("tasterr_session", token)
    return client


def _body(kind: str = "detail_open", retract: bool = False) -> dict[str, object]:
    return {"media_type": "movie", "tmdb_id": 42, "kind": kind, "retract": retract}


def test_unauthenticated_signal_is_rejected(tmp_path: Path) -> None:
    with _client(_app(tmp_path)) as client:
        response = client.post("/api/v1/signals", json=_body())

    assert response.status_code == 401
    assert _stored_signals(tmp_path / "tasterr.db") == []


def test_cross_origin_signal_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/signals", json=_body(), headers={"origin": "https://evil.example"}
        )

    assert response.status_code == 403
    assert _stored_signals(tmp_path / "tasterr.db") == []


def test_rate_limited_signal_record_and_retract_have_no_side_effect(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token = _seed_session(db_path)
    with _client(app, token) as client:
        added = client.post("/api/v1/signals", json=_body("watchlist"))
        assert added.status_code == 200
        app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)

        rejected_retract = client.post("/api/v1/signals", json=_body("watchlist", retract=True))
        rejected_record = client.post("/api/v1/signals", json=_body("detail_open"))

    assert rejected_retract.status_code == 429
    assert rejected_record.status_code == 429
    assert _stored_signals(db_path) == [("movie", 42, "watchlist")]


def test_server_recorded_kinds_are_unrepresentable(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        for kind in ("request", "seed_request_history", "watched_plex", "bogus"):
            response = client.post("/api/v1/signals", json=_body(kind))
            assert response.status_code == 422, kind

    assert _stored_signals(tmp_path / "tasterr.db") == []


def test_retracting_an_append_only_kind_is_rejected(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post("/api/v1/signals", json=_body("detail_open", retract=True))

    assert response.status_code == 422


def test_watchlist_add_then_retract_round_trip(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        added = client.post("/api/v1/signals", json=_body("watchlist"))
        assert added.status_code == 200
        assert added.json() == {"recorded": True}

        readd = client.post("/api/v1/signals", json=_body("watchlist"))
        assert readd.json() == {"recorded": False}  # idempotent, still success

        retracted = client.post("/api/v1/signals", json=_body("watchlist", retract=True))
        assert retracted.status_code == 200

    assert _stored_signals(tmp_path / "tasterr.db") == []


def test_not_interested_add_then_undo_round_trip(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        hidden = client.post("/api/v1/signals", json=_body("not_interested"))
        assert hidden.status_code == 200
        assert hidden.json() == {"recorded": True}

        undone = client.post("/api/v1/signals", json=_body("not_interested", retract=True))
        assert undone.status_code == 200

    assert _stored_signals(tmp_path / "tasterr.db") == []


def test_same_day_detail_open_dedupes(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        first = client.post("/api/v1/signals", json=_body("detail_open"))
        second = client.post("/api/v1/signals", json=_body("detail_open"))

    assert first.json() == {"recorded": True}
    assert second.json() == {"recorded": False}
    assert _stored_signals(tmp_path / "tasterr.db") == [("movie", 42, "detail_open")]

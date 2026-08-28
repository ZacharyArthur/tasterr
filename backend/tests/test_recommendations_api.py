# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import cast

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tasterr.api.taste import import_plex_history
from tasterr.auth.crypto import encrypt_token
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.catalog.models import MediaSummary
from tasterr.catalog.plex import PlexCatalogService, PlexHistoryResult
from tasterr.clients.errors import UpstreamUnavailable
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.db.runtime_settings import save_runtime_settings
from tasterr.main import create_app
from tasterr.recommend import store
from tasterr.recommend.features import FeatureRecord
from tasterr.recommend.service import TasteService
from tasterr.runtime_settings import RailType, RuntimeSettings
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


def _seed_session(
    db_path: Path, seerr_user_id: int = SEERR_USER_ID, *, plex: bool = False
) -> tuple[str, int]:
    token_and_id: list[tuple[str, int]] = []

    async def _go() -> None:
        engine = create_engine(db_path)
        try:
            await upgrade_to_head(engine)
            maker = async_sessionmaker(engine, expire_on_commit=False)
            async with maker() as db:
                user = User(
                    seerr_user_id=seerr_user_id,
                    display_name="member",
                    auth_type="plex" if plex else "local",
                )
                db.add(user)
                await db.flush()
                plex_token = encrypt_token("test-secret-key", "plex-token") if plex else None
                token = await mint_session(db, user.id, "connect.sid=s%3Aseed", plex_token)
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


def _summary(tmdb_id: int) -> MediaSummary:
    return MediaSummary(
        id=tmdb_id,
        media_type="movie",
        title=f"Title {tmdb_id}",
        overview="",
        poster_path=None,
        backdrop_path=None,
        year=2026,
        vote_average=7.0,
    )


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
            vector={"genre:drama": 0.8, "kw:heist": 0.6},
            vote_average=8.0,
            vote_count=5000,
            watch_region="US",
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


# ── Household blend contracts ────────────────────────────────────────────────


def test_household_members_are_ordered_allowlisted_and_signal_based(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)

    async def prepare(db: AsyncSession) -> None:
        caller = await db.get(User, caller_id)
        assert caller is not None
        caller.avatar_url = "/caller.png"
        eligible = User(
            seerr_user_id=8,
            display_name="eligible",
            avatar_url="/eligible.png",
            auth_type="plex",
            is_admin=True,
        )
        quiet = User(seerr_user_id=9, display_name="quiet", auth_type="local")
        db.add_all((eligible, quiet))
        await db.flush()
        await store.record_signal(db, caller_id, "movie", 1, "watchlist")
        await store.record_signal(db, eligible.id, "movie", 2, "request")
        await store.save_profile(db, caller_id, {"genre:drama": 1.0})

    _run_db(db_path, prepare)
    with _client(app, token) as client:
        before = client.get("/api/v1/recommendations/household-members")

        async def invalidate(db: AsyncSession) -> None:
            await store.invalidate_profile(db, caller_id)

        _run_db(db_path, invalidate)
        after = client.get("/api/v1/recommendations/household-members")

    assert before.status_code == 200
    assert before.json() == after.json()
    members = before.json()
    assert [member["id"] for member in members] == sorted(member["id"] for member in members)
    assert members == [
        {
            "id": caller_id,
            "display_name": "member",
            "avatar_url": "/caller.png",
            "has_taste_signals": True,
        },
        {
            "id": caller_id + 1,
            "display_name": "eligible",
            "avatar_url": "/eligible.png",
            "has_taste_signals": True,
        },
        {
            "id": caller_id + 2,
            "display_name": "quiet",
            "avatar_url": None,
            "has_taste_signals": False,
        },
    ]


def test_household_members_require_session_and_disabled_gate_skips_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, _ = _seed_session(db_path)

    async def disable(db: AsyncSession) -> None:
        await save_runtime_settings(
            db,
            RuntimeSettings(disabled_rail_types=[RailType.HOUSEHOLD_BLEND]),
        )

    _run_db(db_path, disable)

    async def unexpected_query(*_args: object) -> list[object]:
        raise AssertionError("disabled member query ran")

    monkeypatch.setattr("tasterr.api.recommendations._load_household_members", unexpected_query)
    with _client(app) as anonymous:
        assert anonymous.get("/api/v1/recommendations/household-members").status_code == 401
    with _client(app, token) as client:
        response = client.get("/api/v1/recommendations/household-members")

    assert response.status_code == 200
    assert response.json() == []


def test_household_blend_validates_and_runs_once_for_sorted_audience(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)
    other_id: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        other = User(seerr_user_id=8, display_name="other", auth_type="local")
        db.add(other)
        await db.flush()
        other_id.append(other.id)
        await store.record_signal(db, caller_id, "movie", 1, "request")
        await store.record_signal(db, other.id, "movie", 2, "request")

    _run_db(db_path, prepare)
    audiences: list[list[int]] = []

    async def fake_blend(_self: TasteService, user_ids: list[int]) -> list[MediaSummary]:
        audiences.append(user_ids)
        return [_summary(tmdb_id) for tmdb_id in range(10, 14)]

    monkeypatch.setattr(TasteService, "household_blend", fake_blend)
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [other_id[0], caller_id]},
        )

    assert response.status_code == 200
    assert audiences == [[caller_id, other_id[0]]]
    assert response.json()["id"] == "household-blend"
    assert response.json()["title"] == "Something for Everyone Tonight"
    assert [item["id"] for item in response.json()["items"]] == [10, 11, 12, 13]


@pytest.mark.parametrize(
    "user_ids",
    [[1], [1, 1], [0, 1], [1, 2, 3, 4, 5, 6, 7]],
)
def test_household_blend_body_is_unique_positive_and_bounded(
    tmp_path: Path, user_ids: list[int]
) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/household-blend", json={"user_ids": user_ids}
        )

    assert response.status_code == 422


def test_household_blend_rejects_omitted_caller_and_tasteless_member(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)
    other_ids: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        for seerr_user_id in (8, 9):
            member = User(
                seerr_user_id=seerr_user_id,
                display_name="other",
                auth_type="local",
            )
            db.add(member)
            await db.flush()
            other_ids.append(member.id)
            await store.record_signal(db, member.id, "movie", member.id, "request")
        await store.record_signal(db, caller_id, "movie", 1, "request")

    _run_db(db_path, prepare)
    calls = 0

    async def fake_blend(_self: TasteService, _user_ids: list[int]) -> list[MediaSummary]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(TasteService, "household_blend", fake_blend)
    with _client(app, token) as client:
        omitted = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": other_ids},
        )

        async def remove_signal(db: AsyncSession) -> None:
            await store.delete_user_taste(db, other_ids[0])

        _run_db(db_path, remove_signal)
        tasteless = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [caller_id, other_ids[0]]},
        )

        async def make_caller_tasteless(db: AsyncSession) -> None:
            await store.record_signal(db, other_ids[0], "movie", other_ids[0], "request")
            await store.delete_user_taste(db, caller_id)

        _run_db(db_path, make_caller_tasteless)
        tasteless_caller = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [caller_id, other_ids[0]]},
        )

    assert omitted.status_code == 400
    assert tasteless.status_code == 400
    assert tasteless_caller.status_code == 400
    assert (
        omitted.json()
        == tasteless.json()
        == tasteless_caller.json()
        == {"detail": "Household blend unavailable"}
    )
    assert calls == 0


def test_household_blend_guards_run_before_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)
    calls = 0

    async def fake_blend(_self: TasteService, _user_ids: list[int]) -> list[MediaSummary]:
        nonlocal calls
        calls += 1
        return []

    monkeypatch.setattr(TasteService, "household_blend", fake_blend)
    payload = {"user_ids": [caller_id, caller_id + 1]}
    with _client(app) as anonymous:
        assert (
            anonymous.post("/api/v1/recommendations/household-blend", json=payload).status_code
            == 401
        )
    with _client(app, token) as client:
        assert (
            client.post(
                "/api/v1/recommendations/household-blend",
                json=payload,
                headers={"origin": "https://evil.example"},
            ).status_code
            == 403
        )
        app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)
        assert (
            client.post("/api/v1/recommendations/household-blend", json=payload).status_code == 429
        )

    assert calls == 0


def test_disabled_household_blend_skips_validation_and_computation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)

    async def disable(db: AsyncSession) -> None:
        await save_runtime_settings(
            db,
            RuntimeSettings(disabled_rail_types=[RailType.HOUSEHOLD_BLEND]),
        )

    _run_db(db_path, disable)

    async def unexpected(*_args: object) -> list[int]:
        raise AssertionError("disabled blend work ran")

    monkeypatch.setattr("tasterr.api.recommendations._validate_household_audience", unexpected)
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [caller_id, caller_id + 1]},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Household blend unavailable"}


# ── Reset ───────────────────────────────────────────────────────────────────────────────────


def test_household_blend_failure_is_generic_and_log_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)
    other_id: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        other = User(seerr_user_id=8, display_name="other", auth_type="local")
        db.add(other)
        await db.flush()
        other_id.append(other.id)
        await store.record_signal(db, caller_id, "movie", 1, "request")
        await store.record_signal(db, other.id, "movie", 2, "request")

    _run_db(db_path, prepare)
    private_marker = "private-member-profile-marker"

    async def fail(_self: TasteService, _user_ids: list[int]) -> list[MediaSummary]:
        raise RuntimeError(private_marker)

    monkeypatch.setattr(TasteService, "household_blend", fail)
    caplog.set_level("ERROR")
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [caller_id, other_id[0]]},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Household blend unavailable"}
    assert private_marker not in response.text
    assert private_marker not in caplog.text


@pytest.mark.parametrize("failure", ["tmdb", "storage"])
def test_household_blend_tmdb_and_storage_degrade_generically(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, caller_id = _seed_session(db_path)
    other_id: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        other = User(seerr_user_id=8, display_name="other", auth_type="local")
        db.add(other)
        await db.flush()
        other_id.append(other.id)
        await store.record_signal(db, caller_id, "movie", 1, "request")
        await store.record_signal(db, other.id, "movie", 2, "request")

    _run_db(db_path, prepare)

    async def fail(*_args: object, **_kwargs: object) -> object:
        if failure == "tmdb":
            raise UpstreamUnavailable("private upstream detail")
        raise RuntimeError("private storage detail")

    if failure == "tmdb":
        monkeypatch.setattr("tasterr.catalog.service.CatalogService.title_facts", fail)
    else:
        monkeypatch.setattr(store, "load_profile", fail)
    with _client(app, token) as client:
        response = client.post(
            "/api/v1/recommendations/household-blend",
            json={"user_ids": [caller_id, other_id[0]]},
        )

    assert response.status_code == 400
    assert response.json() == {"detail": "Household blend unavailable"}
    assert "private" not in response.text


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
        user = await db.get(User, user_id)
        assert user is not None
        user.plex_history_attempted_at = datetime(2026, 8, 1)
        user.plex_history_synced_at = datetime(2026, 8, 1)

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
        user = await db.get(User, user_id)
        assert user is not None
        assert user.plex_history_attempted_at is None
        assert user.plex_history_synced_at is None

    _run_db(tmp_path / "tasterr.db", verify)


def test_plex_reset_schedules_history_only_after_seerr_seed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path)
    token, _user_id = _seed_session(tmp_path / "tasterr.db", plex=True)
    order: list[str] = []

    async def fake_seed(*_args: object) -> int:
        assert _user_id in app.state.plex_history_resets
        order.append("seed")
        return 0

    def fake_schedule(*_args: object) -> None:
        assert _user_id not in app.state.plex_history_resets
        order.append("plex")

    monkeypatch.setattr("tasterr.api.recommendations.seed_user", fake_seed)
    monkeypatch.setattr("tasterr.api.recommendations.schedule_plex_history", fake_schedule)
    with _client(app, token) as client:
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 200
    assert order == ["seed", "plex"]
    assert app.state.plex_history_resets == set()


def test_reset_cancels_and_awaits_a_real_hung_plex_import(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, seerr=False)
    db_path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(db_path, plex=True)
    started = Event()
    cancelled = Event()

    class HangingHistory:
        async def history(
            self, _account_token: str, *, viewed_after: int, viewed_before: int
        ) -> PlexHistoryResult:
            assert viewed_after < viewed_before
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                cancelled.set()
                raise
            raise AssertionError("unreachable")

    def ignore_schedule(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.recommendations.schedule_plex_history", ignore_schedule)
    with _client(app, token) as client:

        async def start_import() -> None:
            task = asyncio.create_task(
                import_plex_history(
                    app.state.sessionmaker,
                    cast("PlexCatalogService", HangingHistory()),
                    "test-secret-key",
                    encrypt_token("test-secret-key", "plex-token"),
                    user_id,
                )
            )
            app.state.plex_history_tasks[user_id] = task

        assert client.portal is not None
        client.portal.call(start_import)
        assert started.wait(1)
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 200
    assert response.json() == {"seeded_signals": 0}
    assert cancelled.is_set()
    assert app.state.plex_history_tasks == {}

    async def verify(db: AsyncSession) -> None:
        assert await store.has_signals(db, user_id) is False
        user = await db.get(User, user_id)
        assert user is not None
        assert user.plex_history_attempted_at is None
        assert user.plex_history_synced_at is None

    _run_db(db_path, verify)


def test_reset_clears_attempt_committed_after_session_resolution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app = _app(tmp_path, seerr=False)
    db_path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(db_path, plex=True)
    raced_at = datetime(2026, 8, 28)

    async def commit_after_session_load(_request: object, reset_user_id: int) -> None:
        assert reset_user_id == user_id
        maker = cast("async_sessionmaker[AsyncSession]", app.state.sessionmaker)
        async with maker() as concurrent_db:
            user = await concurrent_db.get(User, user_id)
            assert user is not None
            user.plex_history_attempted_at = raced_at
            user.plex_history_synced_at = raced_at
            await concurrent_db.commit()

    def ignore_schedule(*_args: object) -> None:
        pass

    monkeypatch.setattr(
        "tasterr.api.recommendations.cancel_plex_history", commit_after_session_load
    )
    monkeypatch.setattr("tasterr.api.recommendations.schedule_plex_history", ignore_schedule)
    with _client(app, token) as client:
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 200

    async def verify(db: AsyncSession) -> None:
        user = await db.get(User, user_id)
        assert user is not None
        assert user.plex_history_attempted_at is None
        assert user.plex_history_synced_at is None

    _run_db(db_path, verify)


def test_reset_touches_only_the_caller(tmp_path: Path) -> None:
    app = _app(tmp_path)
    token, _ = _seed_session(tmp_path / "tasterr.db")
    other_id: list[int] = []

    async def prepare(db: AsyncSession) -> None:
        other = User(seerr_user_id=8, display_name="other", auth_type="local")
        db.add(other)
        await db.flush()
        other.plex_history_attempted_at = datetime(2026, 8, 1)
        other.plex_history_synced_at = datetime(2026, 8, 2)
        other_id.append(other.id)
        await store.record_signal(db, other.id, "movie", 1, "watchlist")

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        app.state.http = _mock_http()
        assert client.post("/api/v1/recommendations/reset").status_code == 200

    async def verify(db: AsyncSession) -> None:
        assert await store.has_signals(db, other_id[0]) is True
        other = await db.get(User, other_id[0])
        assert other is not None
        assert other.plex_history_attempted_at == datetime(2026, 8, 1)
        assert other.plex_history_synced_at == datetime(2026, 8, 2)

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


def test_rate_limited_reset_preserves_signals_and_profile(tmp_path: Path) -> None:
    app = _app(tmp_path)
    db_path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(db_path)

    async def prepare(db: AsyncSession) -> None:
        await store.record_signal(db, user_id, "movie", 99, "watchlist")
        await store.save_profile(db, user_id, {"genre:sentinel": 1.0})

    _run_db(db_path, prepare)
    app.state.mutation_bucket = TokenBucket(capacity=0, refill_per_second=0)
    with _client(app, token) as client:
        response = client.post("/api/v1/recommendations/reset")

    assert response.status_code == 429

    async def verify(db: AsyncSession) -> None:
        signals = await store.load_signals(db, user_id)
        assert [(signal.tmdb_id, signal.kind) for signal in signals] == [(99, "watchlist")]
        profile = await store.load_profile(db, user_id)
        assert profile is not None
        assert profile.vector == {"genre:sentinel": 1.0}

    _run_db(db_path, verify)

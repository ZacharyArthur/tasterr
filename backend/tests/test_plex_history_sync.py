import asyncio
from collections.abc import Coroutine
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Never, cast

import pytest
from fastapi import FastAPI
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker
from starlette.requests import Request
from starlette.types import Scope

import tasterr.api.taste as taste_api
from tasterr.api.taste import cancel_plex_history, schedule_plex_history
from tasterr.auth.crypto import encrypt_token
from tasterr.cache import Cache
from tasterr.catalog.plex import PlexCatalogService, PlexHistoryResult, PlexWatch
from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import User
from tasterr.recommend import store
from tasterr.recommend.signals import MediaType, SignalKind
from tasterr.settings import Settings

SECRET = "history-test-secret"


class FakeHistory:
    def __init__(self, result: PlexHistoryResult, maker: async_sessionmaker[AsyncSession]) -> None:
        self.result = result
        self.maker = maker
        self.calls = 0
        self.account_token = ""
        self.viewed_after = 0
        self.viewed_before = 0
        self.attempt_was_committed = False

    async def history(
        self, account_token: str, *, viewed_after: int, viewed_before: int
    ) -> PlexHistoryResult:
        self.calls += 1
        self.account_token = account_token
        self.viewed_after = viewed_after
        self.viewed_before = viewed_before
        async with self.maker() as db:
            attempted = (
                await db.execute(text("select plex_history_attempted_at from users"))
            ).scalar_one()
            self.attempt_was_committed = attempted is not None
        return self.result


async def _database(
    tmp_path: Path, *, synced_at: datetime | None = None
) -> tuple[AsyncEngine, async_sessionmaker[AsyncSession], int]:
    engine = create_engine(tmp_path / "history.db")
    await upgrade_to_head(engine)
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as db:
        user = User(
            seerr_user_id=1,
            display_name="viewer",
            auth_type="plex",
            plex_history_synced_at=synced_at,
        )
        db.add(user)
        await db.commit()
        return engine, maker, user.id


def _watches(count: int) -> tuple[PlexWatch, ...]:
    watched_at = datetime(2026, 8, 1, 12)
    return tuple(PlexWatch("movie", index, watched_at) for index in range(1, count + 1))


async def test_first_import_commits_attempt_before_reads_and_batches_writes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, maker, user_id = await _database(tmp_path)
    history = FakeHistory(PlexHistoryResult(_watches(205), complete=True), maker)
    writes = 0
    commit_sizes: list[int] = []
    original_record = store.record_signal
    original_commit = AsyncSession.commit

    async def tracked_record(
        db: AsyncSession,
        tracked_user_id: int,
        media_type: MediaType,
        tmdb_id: int,
        kind: SignalKind,
        created_at: datetime | None = None,
    ) -> bool:
        nonlocal writes
        writes += 1
        return await original_record(db, tracked_user_id, media_type, tmdb_id, kind, created_at)

    async def tracked_commit(db: AsyncSession) -> None:
        nonlocal writes
        commit_sizes.append(writes)
        writes = 0
        await original_commit(db)

    monkeypatch.setattr(store, "record_signal", tracked_record)
    monkeypatch.setattr(AsyncSession, "commit", tracked_commit)
    try:
        await taste_api.import_plex_history(
            maker,
            cast("PlexCatalogService", history),
            SECRET,
            encrypt_token(SECRET, "account-token"),
            user_id,
        )

        assert history.account_token == "account-token"
        assert history.attempt_was_committed is True
        assert history.viewed_before - history.viewed_after == 365 * 24 * 60 * 60
        assert commit_sizes == [0, 100, 100, 5, 0]
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text("select plex_history_attempted_at, plex_history_synced_at from users")
                )
            ).one()
            assert row[0] == row[1]
            assert (
                await connection.execute(text("select count(*) from signals"))
            ).scalar_one() == 205
    finally:
        await engine.dispose()


async def test_partial_import_persists_facts_without_advancing_overlap_watermark(
    tmp_path: Path,
) -> None:
    previous = datetime(2026, 7, 1, 12)
    engine, maker, user_id = await _database(tmp_path, synced_at=previous)
    history = FakeHistory(PlexHistoryResult(_watches(1), complete=False), maker)
    try:
        await taste_api.import_plex_history(
            maker,
            cast("PlexCatalogService", history),
            SECRET,
            encrypt_token(SECRET, "token"),
            user_id,
        )

        assert history.viewed_after == int(
            (previous - timedelta(hours=24)).replace(tzinfo=UTC).timestamp()
        )
        async with engine.connect() as connection:
            row = (
                await connection.execute(
                    text("select plex_history_attempted_at, plex_history_synced_at from users")
                )
            ).one()
            assert row[0] is not None
            assert datetime.fromisoformat(str(row[1])) == previous
            assert (
                await connection.execute(text("select count(*) from signals"))
            ).scalar_one() == 1
    finally:
        await engine.dispose()


async def test_import_failure_log_omits_private_exception_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    private_marker = "private-account-title-and-token"
    engine, maker, user_id = await _database(tmp_path)
    history = FakeHistory(PlexHistoryResult((), complete=True), maker)

    async def fail_history(
        _account_token: str, *, viewed_after: int, viewed_before: int
    ) -> PlexHistoryResult:
        raise RuntimeError(private_marker)

    history.history = fail_history  # type: ignore[method-assign]
    try:
        caplog.set_level("ERROR", logger="tasterr.taste")
        await taste_api.import_plex_history(
            maker,
            cast("PlexCatalogService", history),
            SECRET,
            encrypt_token(SECRET, "account-token"),
            user_id,
        )

        assert "plex history: import failed" in caplog.text
        assert private_marker not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)
    finally:
        await engine.dispose()


async def test_failed_attempt_commit_runs_no_network_and_leaves_no_timestamp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, maker, user_id = await _database(tmp_path)
    history = FakeHistory(PlexHistoryResult((), complete=True), maker)

    async def fail_commit(_db: AsyncSession) -> None:
        raise RuntimeError("write failed")

    monkeypatch.setattr(AsyncSession, "commit", fail_commit)
    try:
        await taste_api.import_plex_history(
            maker,
            cast("PlexCatalogService", history),
            SECRET,
            encrypt_token(SECRET, "token"),
            user_id,
        )

        assert history.calls == 0
        async with engine.connect() as connection:
            attempted = (
                await connection.execute(text("select plex_history_attempted_at from users"))
            ).scalar_one()
            assert attempted is None
    finally:
        await engine.dispose()


async def test_fresh_database_attempt_suppresses_a_stale_request_import(tmp_path: Path) -> None:
    engine, maker, user_id = await _database(tmp_path)
    recent = datetime.now(UTC).replace(tzinfo=None)
    async with maker() as db:
        user = await db.get(User, user_id)
        assert user is not None
        user.plex_history_attempted_at = recent
        await db.commit()
    history = FakeHistory(PlexHistoryResult((), complete=True), maker)
    try:
        await taste_api.import_plex_history(
            maker,
            cast("PlexCatalogService", history),
            SECRET,
            encrypt_token(SECRET, "token"),
            user_id,
        )

        assert history.calls == 0
        async with maker() as db:
            user = await db.get(User, user_id)
            assert user is not None
            assert user.plex_history_attempted_at == recent
    finally:
        await engine.dispose()


def _request() -> Request:
    app = FastAPI()
    app.state.plex_history_tasks = {}
    app.state.plex_history_resets = set()
    app.state.seeding = set()
    app.state.sessionmaker = object()
    app.state.catalog_cache = Cache()
    app.state.http = object()
    scope = cast(
        "Scope",
        {
            "type": "http",
            "app": app,
            "method": "GET",
            "path": "/",
            "headers": [],
            "query_string": b"",
            "server": ("testserver", 80),
            "client": ("testclient", 1),
            "scheme": "http",
        },
    )
    return Request(scope)


async def test_scheduler_is_single_flight_and_waits_for_seerr_seed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    request.app.state.seeding.add(1)
    called = asyncio.Event()

    async def fake_import(*_args: object) -> None:
        called.set()

    monkeypatch.setattr(taste_api, "import_plex_history", fake_import)
    settings = Settings.model_validate({"tasterr_secret_key": SECRET})

    schedule_plex_history(request, settings, 1, None, "ciphertext")
    schedule_plex_history(request, settings, 1, None, "ciphertext")
    tasks = request.app.state.plex_history_tasks
    assert len(tasks) == 1
    task = tasks[1]
    await asyncio.sleep(0.1)
    assert called.is_set() is False

    request.app.state.seeding.remove(1)
    await task
    assert called.is_set() is True
    assert request.app.state.plex_history_tasks == {}


async def test_recent_attempt_and_failed_task_creation_do_not_run_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request = _request()
    settings = Settings.model_validate({"tasterr_secret_key": SECRET})
    called = False

    async def fake_import(*_args: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr(taste_api, "import_plex_history", fake_import)
    schedule_plex_history(request, settings, 1, datetime.now(), "ciphertext")
    assert request.app.state.plex_history_tasks == {}

    def fail_create(_coroutine: Coroutine[object, object, None]) -> Never:
        raise RuntimeError("task creation failed")

    with monkeypatch.context() as context:
        context.setattr(taste_api.asyncio, "create_task", fail_create)
        schedule_plex_history(request, settings, 1, None, "ciphertext")

    assert called is False
    assert request.app.state.plex_history_tasks == {}


def test_scheduler_does_not_replace_a_reset_owned_import() -> None:
    request = _request()
    request.app.state.plex_history_resets.add(1)

    schedule_plex_history(
        request,
        Settings.model_validate({"tasterr_secret_key": SECRET}),
        1,
        None,
        "ciphertext",
    )

    assert request.app.state.plex_history_tasks == {}


async def test_cancel_plex_history_awaits_and_releases_the_user_task() -> None:
    request = _request()
    started = asyncio.Event()

    async def hanging() -> None:
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(hanging())
    request.app.state.plex_history_tasks[1] = task
    await started.wait()

    await cancel_plex_history(request, 1)

    assert task.cancelled()
    assert request.app.state.plex_history_tasks == {}

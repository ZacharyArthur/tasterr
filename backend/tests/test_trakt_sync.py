import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, timedelta
from pathlib import Path

import httpx
import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_auth_api import SECRET
from tests.trakt_fixtures import entry, trakt_harness

from tasterr.api.taste import history_guard, import_trakt_history, schedule_history
from tasterr.auth.crypto import decrypt_token
from tasterr.auth.login import get_link
from tasterr.auth.trakt import TraktCredential
from tasterr.clients.trakt import TraktClient
from tasterr.db.models import utcnow
from tasterr.recommend import store


async def test_first_sync_all_time_attempt_committed_and_100_fact_batches(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        fixture.settings.tasterr_watch_history_days = 1
        await fixture.seed()
        fixture.upstream.pages = {("movies", 1): [entry(i, days=365 * 3) for i in range(1, 206)]}

        async def on_read(request: httpx.Request) -> None:
            assert "start_at" not in request.url.params
            async with fixture.maker() as db:
                link = await get_link(db, 1, "trakt")
                assert link is not None and link.sync_attempted_at is not None

        fixture.upstream.on_read = on_read
        original = AsyncSession.commit
        totals: list[int] = []

        async def commit(db: AsyncSession) -> None:
            totals.append(len(await store.load_signals(db, 1)))
            await original(db)

        monkeypatch.setattr(AsyncSession, "commit", commit)
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        assert totals == [0, 0, 100, 200, 205, 205]
        async with fixture.maker() as db:
            rows = await store.load_signals(db, 1)
            assert len(rows) == 205 and all(row.kind == "watched_trakt" for row in rows)
            assert all(row.created_at < utcnow() - timedelta(days=1000) for row in rows)
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.sync_synced_at is not None


@pytest.mark.parametrize(
    "mode,pages,unique",
    [
        ("title-cap", 2, 500),
        ("page-cap", 10, 1),
        ("clamped", 5, 500),
        ("short", 2, 251),
        ("empty", 2, 250),
        ("count-wins", 3, 3),
    ],
)
async def test_pagination_bounds_and_headers(
    tmp_path: Path, mode: str, pages: int, unique: int
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        fake = fixture.upstream
        fake.pages = {}
        fake.page_count = (
            100 if mode in ("title-cap", "page-cap") else (3 if mode == "count-wins" else None)
        )
        fake.page_limit = 100 if mode == "clamped" else None
        for number in range(1, 12):
            count = 100 if mode == "clamped" else 250
            if mode == "count-wins" or (number == 2 and mode == "short"):
                count = 1
            if number == 2 and mode == "empty":
                count = 0
            stride = 100 if mode == "clamped" else 250
            fake.pages[("movies", number)] = [
                entry(1 if mode == "page-cap" else (number - 1) * stride + i + 1)
                for i in range(count)
            ]
            fake.pages[("episodes", number)] = [
                entry(1 if mode == "page-cap" else (number - 1) * stride + i + 1, show=True)
                for i in range(count)
            ]
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        movie_reads = [r for r in fake.requests if r.url.path == "/sync/history/movies"]
        assert len(movie_reads) == pages
        async with fixture.maker() as db:
            rows = await store.load_signals(db, 1)
            assert len([row for row in rows if row.media_type == "movie"]) == unique
            assert len([row for row in rows if row.media_type == "tv"]) == unique
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.sync_synced_at is not None


@pytest.mark.parametrize("missing", [False, True])
async def test_activity_skip_and_exact_overlap_filter(tmp_path: Path, missing: bool) -> None:
    async with trakt_harness(tmp_path) as fixture:
        synced = utcnow()
        await fixture.seed(synced=synced)
        old = (synced - timedelta(days=3)).replace(tzinfo=UTC).isoformat()
        fixture.upstream.activities = {
            "movies": {"watched_at": old},
            "episodes": {"watched_at": old},
        }
        if missing:
            fixture.upstream.activities.pop("episodes")
        fixture.upstream.pages = {("movies", 1): [entry(1, days=3), entry(2, days=0)]}
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        reads = [r for r in fixture.upstream.requests if r.url.path.startswith("/sync/history/")]
        assert bool(reads) is missing
        assert all(
            r.url.params["start_at"] == (synced - timedelta(days=1)).date().isoformat()
            for r in reads
        )
        async with fixture.maker() as db:
            assert [row.tmdb_id for row in await store.load_signals(db, 1)] == (
                [2] if missing else []
            )
            link = await get_link(db, 1, "trakt")
            assert (
                link is not None
                and link.sync_synced_at is not None
                and link.sync_synced_at >= synced
            )


@pytest.mark.parametrize("expires,refresh", [(-1, True), (240, True), (360, False)])
async def test_refresh_threshold_and_persistence_before_reads(
    tmp_path: Path, expires: int, refresh: bool
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed(expires=expires)

        async def verify(request: httpx.Request) -> None:
            async with fixture.maker() as db:
                link = await get_link(db, 1, "trakt")
                assert link is not None and link.credential_enc is not None
                credential = TraktCredential.model_validate_json(
                    decrypt_token(SECRET, link.credential_enc)
                )
                assert credential.access_token == (
                    "rotated-access" if refresh else "original-access"
                )
                assert request.headers["authorization"] == "Bearer " + credential.access_token

        fixture.upstream.on_read = verify
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        assert fixture.upstream.refresh_started.is_set() is refresh
        async with fixture.maker() as db:
            assert len(await store.load_signals(db, 1)) == 2


@pytest.mark.parametrize("status", [400, 503])
async def test_refresh_failure_keeps_link_watermark_and_logs_no_credentials(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        synced = utcnow() - timedelta(days=2)
        await fixture.seed(expires=-1, synced=synced)
        fixture.upstream.refresh_status = status
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.sync_synced_at == synced
        assert "trakt history: import failed" in caplog.text
        assert all(
            s not in caplog.text
            for s in ("original-access", "original-refresh", "client-fixture", SECRET)
        )


@pytest.mark.parametrize("action", ["deadline", "reset", "unlink"])
async def test_slow_refresh_stream_cannot_hold_cancellation_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, action: str
) -> None:
    monkeypatch.setattr("tasterr.clients.trakt.TIMEOUT_SECONDS", 0.1)
    if action == "deadline":
        monkeypatch.setattr("tasterr.api.taste.TRAKT_SYNC_TIMEOUT", 0.03)

    async def no_restart(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.recommendations.schedule_history", no_restart)
    started = asyncio.Event()
    closed = asyncio.Event()

    class SlowTokens(httpx.AsyncByteStream):
        async def __aiter__(self) -> AsyncIterator[bytes]:
            started.set()
            yield b'{"access_token":"'
            for _ in range(100):
                await asyncio.sleep(0.01)
                yield b"x"

        async def aclose(self) -> None:
            closed.set()

    async with trakt_harness(tmp_path) as fixture:
        synced = utcnow() - timedelta(days=2)
        await fixture.seed(expires=-1, synced=synced)
        original = fixture.upstream.respond

        async def respond(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/oauth/token":
                return httpx.Response(200, stream=SlowTokens())
            return await original(request)

        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
            client = TraktClient(http, "client-fixture")
            task = asyncio.create_task(import_trakt_history(fixture.maker, client, SECRET, 1))
            fixture.app.state.trakt_history_tasks[1] = task
            try:
                async with asyncio.timeout(2):
                    await started.wait()
                    began = asyncio.get_running_loop().time()
                    if action == "deadline":
                        await task
                    else:
                        path = (
                            "/recommendations/reset"
                            if action == "reset"
                            else "/account/links/trakt/unlink"
                        )
                        response = await fixture.client.post("/api/v1" + path, json={})
                        assert response.status_code == 204
                    assert task.done() and closed.is_set()
                    assert asyncio.get_running_loop().time() - began < 0.75
            finally:
                if not task.done():
                    task.cancel()
                await asyncio.gather(task, return_exceptions=True)
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            if action == "unlink":
                assert link is None
            else:
                assert link is not None and link.credential_enc is not None
                credential = TraktCredential.model_validate_json(
                    decrypt_token(SECRET, link.credential_enc)
                )
                assert credential.access_token == "original-access"
                assert link.sync_synced_at == (None if action == "reset" else synced)
            assert not await store.load_signals(db, 1)


@pytest.mark.parametrize(
    "action", ["cancel-three-times", "deadline", "reset", "unlink", "delete", "relink", "shutdown"]
)
async def test_refresh_survives_cancellation_and_mutations_wait_for_rotation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    async def no_restart(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.recommendations.schedule_history", no_restart)
    monkeypatch.setattr("tasterr.api.account.schedule_history", no_restart)
    context = trakt_harness(tmp_path)
    fixture = await context.__aenter__()
    closed = False
    try:
        await fixture.seed(expires=-1)
        fixture.upstream.refresh_release.clear()
        if action == "deadline":
            monkeypatch.setattr("tasterr.api.taste.TRAKT_SYNC_TIMEOUT", 0.01)
        task = asyncio.create_task(
            import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        )
        fixture.app.state.trakt_history_tasks[1] = task
        await fixture.upstream.refresh_started.wait()
        operation: asyncio.Task[object] | None = None
        if action == "cancel-three-times":
            for _ in range(3):
                task.cancel()
                await asyncio.sleep(0)
        elif action == "deadline":
            await asyncio.sleep(0.03)
        elif action == "shutdown":
            operation = asyncio.create_task(context.__aexit__(None, None, None))
            closed = True
        elif action == "relink":
            handle = await fixture.create_handle()
            operation = asyncio.create_task(fixture.poll(handle))
        else:
            path = {
                "reset": "/recommendations/reset",
                "unlink": "/account/links/trakt/unlink",
                "delete": "/account/delete",
            }[action]
            operation = asyncio.create_task(
                fixture.client.post(
                    "/api/v1" + path, json={"confirm": "Viewer"} if action == "delete" else {}
                )
            )
        await asyncio.sleep(0.03)
        assert not task.done()
        if operation is not None:
            assert not operation.done()
        fixture.upstream.refresh_release.set()
        await asyncio.gather(task, return_exceptions=True)
        if operation is not None:
            result = await operation
            if isinstance(result, httpx.Response):
                assert result.status_code in (200, 204)
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            if action in ("unlink", "delete"):
                assert link is None
                revoked = [r for r in fixture.upstream.requests if r.url.path == "/oauth/revoke"]
                assert len(revoked) == 1 and b"rotated-access" in revoked[0].content
            else:
                assert link is not None and link.credential_enc is not None
                credential = TraktCredential.model_validate_json(
                    decrypt_token(SECRET, link.credential_enc)
                )
                assert credential.access_token == (
                    "device-access" if action == "relink" else "rotated-access"
                )
            assert not await store.load_signals(db, 1)
    finally:
        fixture.upstream.refresh_release.set()
        if not closed:
            await context.__aexit__(None, None, None)


async def test_concurrent_type_reads_deadline_and_failed_type_cleanup(tmp_path: Path) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        fake = fixture.upstream
        fake.pages = {
            (kind, page): [entry(1 if kind == "movies" else 2, show=kind == "episodes")] * 250
            for kind in ("movies", "episodes")
            for page in range(1, 11)
        }
        fake.page_count = 10
        fake.delay = 0.02
        arrivals: dict[int, set[str]] = {}
        gates: dict[int, asyncio.Event] = {}

        async def pair_reads(request: httpx.Request) -> None:
            page = int(request.url.params["page"])
            kinds = arrivals.setdefault(page, set())
            gate = gates.setdefault(page, asyncio.Event())
            kinds.add(request.url.path.rsplit("/", 1)[-1])
            if len(kinds) == 2:
                gate.set()
            await gate.wait()

        fake.on_read = pair_reads
        async with asyncio.timeout(5):
            await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        assert len(arrivals) == 10 and all(
            kinds == {"movies", "episodes"} for kinds in arrivals.values()
        )
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.sync_synced_at is not None
            baseline = {
                (row.media_type, row.tmdb_id, row.created_at)
                for row in await store.load_signals(db, 1)
            }
            assert {(media, tmdb_id) for media, tmdb_id, _ in baseline} == {("movie", 1), ("tv", 2)}
        await fixture.unthrottle()
        fake.delay = 0

        async def fail_and_hang(request: httpx.Request) -> None:
            if request.url.path.endswith("movies"):
                await asyncio.sleep(0.01)
                raise RuntimeError("fixture read failure")
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                fake.history_cancelled.set()
                raise

        fake.on_read = fail_and_hang
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        assert fake.history_cancelled.is_set()
        async with fixture.maker() as db:
            assert {
                (row.media_type, row.tmdb_id, row.created_at)
                for row in await store.load_signals(db, 1)
            } == baseline


@pytest.mark.parametrize(
    "mode", ["source-off", "unconfigured", "throttled", "guard", "single-flight", "wait-seerr"]
)
async def test_trigger_eligibility_and_single_flight(tmp_path: Path, mode: str) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        if mode == "source-off":
            async with fixture.maker() as db:
                await store.set_source_enabled(db, 1, "trakt", False)
                await db.commit()
        if mode == "unconfigured":
            fixture.settings.trakt_client_id = None
        if mode == "throttled":
            async with fixture.maker() as db:
                link = await get_link(db, 1, "trakt")
                assert link is not None
                link.sync_attempted_at = utcnow()
                await db.commit()
        request = Request({"type": "http", "app": fixture.app})
        if mode == "wait-seerr":
            fixture.app.state.seeding.add(1)
        fixture.upstream.history_release.clear()
        async with fixture.maker() as db:
            if mode == "guard":
                async with history_guard(request, 1):
                    await schedule_history(request, fixture.settings, db, 1)
            else:
                await schedule_history(request, fixture.settings, db, 1)
                await schedule_history(request, fixture.settings, db, 1)
        tasks = fixture.app.state.trakt_history_tasks
        if mode in ("single-flight", "wait-seerr"):
            assert len(tasks) == 1
            if mode == "wait-seerr":
                await asyncio.sleep(0.02)
                assert not fixture.upstream.history_started.is_set()
                fixture.app.state.seeding.discard(1)
            await fixture.upstream.history_started.wait()
            fixture.upstream.history_release.set()
            await asyncio.gather(*tasks.values())
        else:
            assert not tasks and not fixture.upstream.history_started.is_set()


@pytest.mark.parametrize("action", ["reset", "unlink", "delete", "switch-off", "clear", "shutdown"])
async def test_mutations_and_shutdown_cancel_and_await_history_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    action: str,
) -> None:
    async def no_restart(*_args: object, **_kwargs: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.recommendations.schedule_history", no_restart)
    context = trakt_harness(tmp_path)
    fixture = await context.__aenter__()
    closed = False
    try:
        await fixture.seed()
        fixture.upstream.history_release.clear()
        task = asyncio.create_task(
            import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        )
        fixture.app.state.trakt_history_tasks[1] = task
        await fixture.upstream.history_started.wait()
        assert (await fixture.client.get("/api/v1/taste-onboarding")).json() == {"state": "pending"}
        if action == "shutdown":
            await context.__aexit__(None, None, None)
            closed = True
        else:
            paths = {
                "reset": "/recommendations/reset",
                "unlink": "/account/links/trakt/unlink",
                "delete": "/account/delete",
                "switch-off": "/account/taste-sources",
                "clear": "/account/taste-sources/trakt/clear",
            }
            payload: dict[str, object] = (
                {"source": "trakt", "enabled": False}
                if action == "switch-off"
                else {"confirm": "Viewer"}
                if action == "delete"
                else {}
            )
            assert (
                await fixture.client.post("/api/v1" + paths[action], json=payload)
            ).status_code == 204
        assert task.cancelled() and fixture.upstream.history_cancelled.is_set()
        async with fixture.maker() as db:
            assert not await store.load_signals(db, 1)
    finally:
        if not closed:
            await context.__aexit__(None, None, None)


@pytest.mark.parametrize("mode", ["first-page", "later-page", "deadline"])
async def test_read_failures_keep_watermark_and_throttle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mode: str
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        synced = utcnow() - timedelta(days=2)
        await fixture.seed(synced=synced)
        fixture.upstream.page_count = 2
        fixture.upstream.fail_page = ("movies", 2 if mode == "later-page" else 1)
        if mode == "deadline":
            fixture.upstream.history_release.clear()
            monkeypatch.setattr("tasterr.api.taste.TRAKT_SYNC_TIMEOUT", 0.03)
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        count = len(fixture.upstream.requests)
        await import_trakt_history(fixture.maker, fixture.trakt_client, SECRET, 1)
        assert len(fixture.upstream.requests) == count
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert (
                link is not None
                and link.sync_synced_at == synced
                and link.sync_attempted_at is not None
            )
            assert not await store.load_signals(db, 1)


@pytest.mark.parametrize("action", ["reset", "source-on"])
async def test_home_and_sign_in_schedule_import_and_source_reenable_restarts_all_time(
    tmp_path: Path,
    action: str,
) -> None:
    from typing import cast

    from tests.test_account_api import LOCAL
    from tests.test_browse_api import FakeCatalog  # pyright: ignore[reportPrivateUsage]

    from tasterr.api.catalog import get_catalog
    from tasterr.catalog.service import CatalogService

    async with trakt_harness(tmp_path) as fixture:
        fixture.app.dependency_overrides[get_catalog] = lambda: cast(
            "CatalogService", FakeCatalog()
        )
        await fixture.seed()
        fixture.upstream.fail_page = ("movies", 1)
        assert (await fixture.client.get("/api/v1/home")).status_code == 200
        await asyncio.gather(*fixture.app.state.trakt_history_tasks.values())
        assert fixture.upstream.history_started.is_set()
        assert (await fixture.client.get("/api/v1/home")).status_code == 200
        fixture.upstream.fail_page = None
        await fixture.unthrottle()
        fixture.upstream.history_started.clear()
        assert (await fixture.client.post("/api/v1/auth/local", json=LOCAL)).status_code == 200
        await asyncio.gather(*fixture.app.state.trakt_history_tasks.values())
        assert fixture.upstream.history_started.is_set()
        if action == "source-on":
            assert (
                await fixture.client.post(
                    "/api/v1/account/taste-sources", json={"source": "trakt", "enabled": False}
                )
            ).status_code == 204
        fixture.upstream.requests.clear()
        response = (
            await fixture.client.post(
                "/api/v1/account/taste-sources", json={"source": "trakt", "enabled": True}
            )
            if action == "source-on"
            else await fixture.client.post("/api/v1/recommendations/reset")
        )
        assert response.status_code == 204
        await asyncio.gather(*fixture.app.state.trakt_history_tasks.values())
        reads = [r for r in fixture.upstream.requests if r.url.path.startswith("/sync/history/")]
        assert reads and all("start_at" not in r.url.params for r in reads)

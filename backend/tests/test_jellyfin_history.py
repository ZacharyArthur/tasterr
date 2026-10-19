# pyright: reportPrivateUsage=false
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_clients_jellyfin import KEY, USER_ID
from tests.test_plex_history_sync import _database, _request

from tasterr.api.taste import import_jellyfin_history, schedule_jellyfin_history
from tasterr.auth.login import get_link
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.db.models import LinkedAccount
from tasterr.recommend import store
from tasterr.recommend.jellyfin_history import JellyfinHistoryResult, read_history
from tasterr.settings import Settings

CUTOFF = datetime(2026, 10, 18, 12)
PLAYED = CUTOFF - timedelta(days=1)


async def test_partial_import_commits_at_most_100_facts_and_keeps_watermark(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    engine, maker, user_id = await _database(tmp_path)
    async with maker() as db:
        db.add(
            LinkedAccount(
                user_id=user_id, provider="jellyfin", external_id=USER_ID, display_name="Viewer"
            )
        )
        await db.commit()
    result = JellyfinHistoryResult({("movie", index): PLAYED for index in range(1, 206)}, False)

    async def read(*_args: object) -> JellyfinHistoryResult:
        return result

    monkeypatch.setattr("tasterr.api.taste.read_history", read)
    original_commit = AsyncSession.commit
    totals: list[int] = []

    async def commit(db: AsyncSession) -> None:
        totals.append(len(await store.load_signals(db, user_id)))
        await original_commit(db)

    monkeypatch.setattr(AsyncSession, "commit", commit)
    try:
        await import_jellyfin_history(maker, cast(JellyfinClient, object()), user_id)
        assert totals == [0, 0, 100, 200, 205]
        async with maker() as db:
            link = await get_link(db, user_id, "jellyfin")
            assert link is not None and link.sync_synced_at is None
    finally:
        await engine.dispose()


def item(
    index: int, tmdb: str = "550", played: datetime | None = PLAYED, series: str | None = None
) -> dict[str, object]:
    return {
        "Id": f"{index:032x}",
        "ProviderIds": {"Tmdb": tmdb},
        "UserData": {"LastPlayedDate": played.isoformat() + "Z" if played else None},
        "SeriesId": series,
    }


async def test_mapping_windows_episodes_collapse_and_missing_values() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/Items" and request.url.params["userId"] == USER_ID
        if "Ids" in request.url.params:
            assert request.url.params["Ids"] == f"{100:032x}"
            items = [item(100, "1399")]
        elif request.url.params["IncludeItemTypes"] == "Movie":
            items = [
                item(6, "552", CUTOFF + timedelta(days=1)),
                item(1),
                item(2, "551", None),
                item(3, "0"),
                item(4, "2147483648"),
                item(5, "bad"),
                item(7, "553", CUTOFF - timedelta(days=400)),
            ]
        else:
            items = [
                item(10, "9999", PLAYED, f"{100:032x}"),
                item(12, "7777"),
                item(11, "8888", PLAYED - timedelta(days=1), f"{100:032x}"),
            ]
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": len(items)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await read_history(
            JellyfinClient(http, "http://jellyfin", KEY, "device"),
            USER_ID,
            CUTOFF - timedelta(days=365),
            CUTOFF,
        )
    assert result.complete and result.watches == {("movie", 550): PLAYED, ("tv", 1399): PLAYED}


async def test_pagination_caps_and_series_batches() -> None:
    pages: list[tuple[str, int]] = []
    batches: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if "Ids" in request.url.params:
            ids = request.url.params["Ids"].split(",")
            batches.append(len(ids))
            items = [
                {"Id": series_id, "ProviderIds": {"Tmdb": str(10000 + int(series_id, 16))}}
                for series_id in ids
            ]
            return httpx.Response(200, json={"Items": items, "TotalRecordCount": len(items)})
        kind, offset = request.url.params["IncludeItemTypes"], int(request.url.params["StartIndex"])
        pages.append((kind, offset))
        items = [
            item(
                index, str(index + 1), series=f"{index + 1000:032x}" if kind == "Episode" else None
            )
            for index in range(offset, offset + 100)
        ]
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": 5000})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await read_history(
            JellyfinClient(http, "http://jellyfin", KEY, "device"),
            USER_ID,
            CUTOFF - timedelta(days=365),
            CUTOFF,
        )
    assert result.complete and len(result.watches) == 1000
    assert pages == [
        (kind, offset) for kind in ("Movie", "Episode") for offset in range(0, 500, 100)
    ]
    assert batches == [100] * 5


@pytest.mark.parametrize("kind", ["Movie", "Episode"])
@pytest.mark.parametrize("cross_page", [False, True])
async def test_unordered_plays_keep_watermark_and_do_not_stop_at_old_play(
    kind: str, cross_page: bool
) -> None:
    start = CUTOFF - timedelta(days=365)
    dates = (
        [PLAYED - timedelta(minutes=index) for index in range(100)]
        + [PLAYED + timedelta(hours=1) - timedelta(minutes=index) for index in range(50)]
        if cross_page
        else [start - timedelta(days=1) + timedelta(days=index) for index in range(150)]
    )
    offsets: list[int] = []

    def respond(request: httpx.Request) -> httpx.Response:
        if "Ids" in request.url.params:
            items = [
                {"Id": series_id, "ProviderIds": {"Tmdb": str(int(series_id, 16) - 999)}}
                for series_id in request.url.params["Ids"].split(",")
            ]
            return httpx.Response(200, json={"Items": items, "TotalRecordCount": len(items)})
        if request.url.params["IncludeItemTypes"] != kind:
            return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})
        offset = int(request.url.params["StartIndex"])
        offsets.append(offset)
        items = [
            item(
                index + 1,
                str(index + 1),
                dates[index],
                f"{index + 1000:032x}" if kind == "Episode" else None,
            )
            for index in range(offset, min(offset + 100, len(dates)))
        ]
        return httpx.Response(200, json={"Items": items, "TotalRecordCount": len(dates)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await read_history(
            JellyfinClient(http, "http://jellyfin", KEY, "device"), USER_ID, start, CUTOFF
        )
    media_type = "movie" if kind == "Movie" else "tv"
    assert not result.complete
    assert result.watches == {
        (media_type, index + 1): played
        for index, played in enumerate(dates)
        if start <= played <= CUTOFF
    }
    assert offsets == [0, 100]


async def test_deadline_retains_mapped_facts_without_complete_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("tasterr.recommend.jellyfin_history.HISTORY_DEADLINE_SECONDS", 0.01)

    async def respond(request: httpx.Request) -> httpx.Response:
        if request.url.params["IncludeItemTypes"] == "Episode":
            await asyncio.Event().wait()
        return httpx.Response(200, json={"Items": [item(1)], "TotalRecordCount": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await read_history(
            JellyfinClient(http, "http://jellyfin", KEY, "device"),
            USER_ID,
            CUTOFF - timedelta(days=365),
            CUTOFF,
        )
    assert not result.complete and result.watches == {("movie", 550): PLAYED}


@pytest.mark.parametrize("incremental", [False, True])
@pytest.mark.parametrize("outage", [False, True])
async def test_import_attempt_throttle_windows_watermark_and_outage(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, incremental: bool, outage: bool
) -> None:
    engine, maker, user_id = await _database(tmp_path)
    previous = CUTOFF - timedelta(days=2)
    async with maker() as db:
        db.add(
            LinkedAccount(
                user_id=user_id,
                provider="jellyfin",
                external_id=USER_ID,
                display_name="Viewer",
                sync_synced_at=previous if incremental else None,
            )
        )
        await db.commit()
    monkeypatch.setattr("tasterr.api.taste.utcnow", lambda: CUTOFF)
    windows: list[tuple[datetime, datetime]] = []

    async def read(
        _client: JellyfinClient, external_id: str, start: datetime, cutoff: datetime
    ) -> JellyfinHistoryResult:
        assert external_id == USER_ID
        async with maker() as db:
            link = await get_link(db, user_id, "jellyfin")
            assert link is not None and link.sync_attempted_at == CUTOFF
        windows.append((start, cutoff))
        if outage:
            raise TimeoutError("outage")
        return JellyfinHistoryResult({("movie", 550): PLAYED}, True)

    monkeypatch.setattr("tasterr.api.taste.read_history", read)
    try:
        await import_jellyfin_history(maker, cast(JellyfinClient, object()), user_id)
        await import_jellyfin_history(maker, cast(JellyfinClient, object()), user_id)
        assert windows == [
            (
                previous - timedelta(hours=24) if incremental else CUTOFF - timedelta(days=365),
                CUTOFF,
            )
        ]
        async with maker() as db:
            link = await get_link(db, user_id, "jellyfin")
            assert link is not None
            expected = (previous if incremental else None) if outage else CUTOFF
            assert link.sync_synced_at == expected
            assert len(await store.load_signals(db, user_id)) == int(not outage)
    finally:
        await engine.dispose()


async def test_scheduler_waits_on_seerr_is_single_flight_and_respects_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    request: Request = _request()
    tasks: dict[int, asyncio.Task[None]] = {}
    request.app.state.jellyfin_history_tasks = tasks
    request.app.state.seeding.add(1)
    settings = Settings.model_validate(
        {
            "jellyfin_internal_url": "http://jellyfin",
            "jellyfin_api_key": KEY,
            "tasterr_secret_key": "secret",
        }
    )
    calls: list[int] = []

    async def imported(*_args: object) -> None:
        calls.append(1)

    monkeypatch.setattr("tasterr.api.taste.import_jellyfin_history", imported)
    for _ in range(2):
        schedule_jellyfin_history(request, settings, 1, None)
    assert len(tasks) == 1
    await asyncio.sleep(0.06)
    assert calls == []
    request.app.state.seeding.clear()
    await tasks[1]
    assert calls == [1] and tasks == {}
    schedule_jellyfin_history(request, settings, 1, datetime.now())
    request.app.state.plex_history_resets.add(1)
    schedule_jellyfin_history(request, settings, 1, None)
    assert tasks == {}

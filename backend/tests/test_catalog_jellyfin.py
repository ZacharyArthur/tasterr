from datetime import UTC, datetime

import httpx
import pytest
from tests.test_clients_jellyfin import KEY, USER_ID

from tasterr.catalog.jellyfin import resume_candidates
from tasterr.catalog.resume import ResumeCandidate, merge
from tasterr.clients.errors import UpstreamRejected
from tasterr.clients.jellyfin import JellyfinClient

PLAYED = "2026-10-18T12:00:00Z"
SERIES = "f" * 32


def item(index: int = 1, **changes: object) -> dict[str, object]:
    return {
        "Id": f"{index:032x}",
        "Type": "Movie",
        "ProviderIds": {"Tmdb": str(index)},
        "RunTimeTicks": 100,
        "UserData": {"PlaybackPositionTicks": 40, "LastPlayedDate": PLAYED},
        **changes,
    }


async def mapped(
    resume: list[dict[str, object]],
    next_up: list[dict[str, object]],
    shows: list[dict[str, object]] | None = None,
    recent: list[dict[str, object]] | None = None,
) -> list[ResumeCandidate]:
    series_calls = 0
    activity_calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal series_calls, activity_calls
        assert request.url.params["userId"] == USER_ID
        if request.url.path == "/UserItems/Resume":
            rows = resume
        elif request.url.path == "/Shows/NextUp":
            rows = next_up
        elif request.url.path == "/Items" and "Filters" in request.url.params:
            activity_calls += 1
            assert request.url.params["IncludeItemTypes"] == "Episode"
            assert request.url.params["Filters"] == "IsPlayed"
            assert request.url.params["Recursive"] == "true"
            assert request.url.params["SortBy"] == "DatePlayed"
            assert request.url.params["SortOrder"] == "Descending"
            assert request.url.params["EnableUserData"] == "true"
            assert request.url.params["Limit"] == "100"
            assert request.url.params["StartIndex"] == "0"
            rows = recent or []
        else:
            assert request.url.path == "/Items"
            series_calls += 1
            expected = list(
                dict.fromkeys(
                    str(row["SeriesId"])
                    for row in [*resume, *next_up]
                    if row.get("Type") == "Episode" and row.get("SeriesId")
                )
            )
            assert request.url.params["Ids"].split(",") == expected
            assert request.url.params["EnableUserData"] == "true"
            rows = shows or []
        return httpx.Response(200, json={"Items": rows, "TotalRecordCount": len(rows)})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        result = await resume_candidates(
            JellyfinClient(http, "http://jellyfin", KEY, "device"), USER_ID
        )
    assert series_calls == (1 if shows is not None else 0)
    assert activity_calls == 1
    return result


async def test_movie_episode_and_next_up_collapse_to_series_with_batched_lookup() -> None:
    episode = item(2, Type="Episode", SeriesId=SERIES, ParentIndexNumber=2, IndexNumber=3)
    next_up = item(3, Type="Episode", SeriesId=SERIES, ParentIndexNumber=2, IndexNumber=4)
    show = item(90, Id=SERIES, Type="Series")
    result = await mapped([item(), episode], [next_up], [show])
    assert [(c.media_type, c.tmdb_id, c.progress_percent, c.context) for c in result] == [
        ("movie", 1, 40, None),
        ("tv", 90, 40, "S2 E3"),
        ("tv", 90, None, "S2 E4"),
    ]
    assert all(c.source_rank == (1, 0) for c in result)
    assert len(merge(result)) == 2
    assert merge(result)[1].context == "S2 E3"
    expected = datetime(2026, 10, 18, 12, tzinfo=UTC).timestamp()
    assert all(c.timestamp == expected for c in result)


@pytest.mark.parametrize(
    "position,runtime,expected",
    [
        (5, 8, 62),
        (1, 100, 1),
        (99, 100, 99),
        (0, 100, None),
        (1, 101, None),
        (100, 100, None),
        (101, 100, None),
        (-1, 100, None),
        (40, 0, None),
        (40, -1, None),
        (None, 100, None),
        (40, None, None),
    ],
)
async def test_resume_progress_is_floored_and_invalid_values_are_omitted(
    position: int | None,
    runtime: int | None,
    expected: int | None,
) -> None:
    result = await mapped(
        [
            item(
                RunTimeTicks=runtime,
                UserData={"PlaybackPositionTicks": position, "LastPlayedDate": PLAYED},
            )
        ],
        [],
    )
    assert [c.progress_percent for c in result] == ([] if expected is None else [expected])


@pytest.mark.parametrize(
    "provider",
    [
        {},
        {"Tmdb": ""},
        {"Tmdb": "0"},
        {"Tmdb": "-1"},
        {"Tmdb": "abc"},
        {"Tmdb": "2147483648"},
        {"Tmdb": "\uff11\uff12"},
        {"Tmdb": "9" * 100},
    ],
)
async def test_missing_or_invalid_tmdb_id_omits_movie_and_series(provider: dict[str, str]) -> None:
    episode = item(Type="Episode", SeriesId=SERIES, ParentIndexNumber=1, IndexNumber=1)
    assert (
        await mapped(
            [item(ProviderIds=provider), episode],
            [],
            [
                item(
                    Id=SERIES,
                    Type="Series",
                    ProviderIds=provider,
                )
            ],
        )
        == []
    )


@pytest.mark.parametrize("season,episode", [(None, 1), (1, None), (-1, 2), (1, -1)])
@pytest.mark.parametrize("next_up", [False, True])
async def test_missing_or_negative_episode_numbers_are_omitted(
    season: int | None,
    episode: int | None,
    next_up: bool,
) -> None:
    row = item(Type="Episode", SeriesId=SERIES, ParentIndexNumber=season, IndexNumber=episode)
    assert await mapped([] if next_up else [row], [row] if next_up else [], [item(Id=SERIES)]) == []


async def test_episode_own_id_is_ignored_and_missing_series_is_omitted() -> None:
    episode = item(Type="Episode", SeriesId=SERIES, ParentIndexNumber=0, IndexNumber=0)
    assert await mapped([episode], [], []) == []
    assert await mapped([item(Type="Episode", ParentIndexNumber=1, IndexNumber=1)], []) == []
    assert await mapped([episode], [], [item(9)]) == []
    result = await mapped([episode], [], [item(9, Id=SERIES)])
    assert result[0].tmdb_id == 9 and result[0].context == "S0 E0"


async def test_next_up_uses_series_activity_then_negative_position_and_ignores_progress() -> None:
    ids = [f"{index:032x}" for index in range(100, 103)]
    rows = [
        item(
            i + 1,
            Type="Episode",
            SeriesId=series_id,
            ParentIndexNumber=1,
            IndexNumber=2,
            RunTimeTicks=0,
            UserData=None,
        )
        for i, series_id in enumerate(ids)
    ]
    shows = [
        item(i + 10, Id=series_id, UserData=None if i != 1 else {"LastPlayedDate": PLAYED})
        for i, series_id in enumerate(ids)
    ]
    result = merge(await mapped([], rows, shows))
    assert [c.tmdb_id for c in result] == [11, 10, 12]
    assert [c.timestamp for c in result[1:]] == [-1, -3]
    assert all(c.progress_percent is None for c in result)


async def test_unsupported_types_undated_resume_and_next_up_movies_are_omitted() -> None:
    assert (
        await mapped(
            [
                item(Type="Audio"),
                item(Type=None),
                item(UserData=None),
                item(UserData={"PlaybackPositionTicks": 40}),
            ],
            [item()],
        )
        == []
    )


async def test_two_fifty_item_reads_make_one_hundred_series_batch() -> None:
    rows = [
        item(i + 1, Type="Episode", SeriesId=f"{i + 100:032x}", ParentIndexNumber=1, IndexNumber=1)
        for i in range(100)
    ]
    shows = [item(i + 1, Id=f"{i + 100:032x}") for i in range(100)]
    result = await mapped(rows[:50], rows[50:], shows)
    assert len(result) == 100


async def test_one_endpoint_failure_discards_source() -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/Shows/NextUp":
            return httpx.Response(500)
        return httpx.Response(200, json={"Items": [item()], "TotalRecordCount": 1})

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:
        with pytest.raises(UpstreamRejected):
            await resume_candidates(JellyfinClient(http, "http://jellyfin", KEY, "device"), USER_ID)


async def test_next_up_uses_latest_played_episode_when_series_date_is_absent() -> None:
    next_up = item(Type="Episode", SeriesId=SERIES, ParentIndexNumber=2, IndexNumber=3)
    recent = [
        item(
            100,
            Type="Episode",
            SeriesId=SERIES,
            UserData={"LastPlayedDate": "2026-10-20T12:00:00Z"},
        ),
        item(
            101,
            Type="Episode",
            SeriesId=SERIES,
            UserData={"LastPlayedDate": "2026-10-21T12:00:00+01:00"},
        ),
        item(102, Type="Episode", SeriesId=SERIES, UserData=None),
        item(103, Type="Episode", UserData={"LastPlayedDate": PLAYED}),
        item(
            104, Type="Movie", SeriesId=SERIES, UserData={"LastPlayedDate": "2026-10-22T12:00:00Z"}
        ),
    ]
    result = await mapped([item()], [next_up], [item(9, Id=SERIES, UserData=None)], recent)
    latest = datetime(2026, 10, 21, 11, tzinfo=UTC).timestamp()
    assert result[1].timestamp == latest
    assert result[1].tmdb_id == 9 and result[1].progress_percent is None
    assert merge(result)[0].tmdb_id == 9


async def test_episode_activity_window_is_one_page_and_does_not_resolve_history_titles() -> None:
    next_up = item(Type="Episode", SeriesId=SERIES, ParentIndexNumber=1, IndexNumber=2)
    recent = [item(i + 100, Type="Episode", SeriesId=f"{i:032x}") for i in range(100)]
    result = await mapped([], [next_up], [item(9, Id=SERIES, UserData=None)], recent)
    assert len(result) == 1 and result[0].tmdb_id == 9 and result[0].timestamp == -1
    with pytest.raises(UpstreamRejected):
        await mapped([], [next_up], [item(9, Id=SERIES)], [*recent, recent[0]])

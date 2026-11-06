import json
from datetime import UTC, datetime, timedelta

import pytest

from tasterr.clients.trakt import HistoryPlay, HistoryType
from tasterr.recommend.signals import MAX_TMDB_ID, TitleKey
from tasterr.recommend.trakt_history import fold_page

NOW = datetime(2026, 10, 30, 12)


def play(tmdb_id: int | None, *, show: bool = False, days: int = 0) -> HistoryPlay:
    return HistoryPlay.model_validate_json(
        json.dumps(
            {
                "watched_at": (NOW - timedelta(days=days)).replace(tzinfo=UTC).isoformat(),
                "show" if show else "movie": {"ids": {"tmdb": tmdb_id}},
                "episode": {"ids": {"tmdb": 999}},
            }
        )
    )


@pytest.mark.parametrize("kind", ["movies", "episodes"])
def test_mapping_ids_missing_times_overlap_and_newest(kind: HistoryType) -> None:
    show = kind == "episodes"
    plays = [
        play(1, show=show),
        play(1, show=show, days=2),
        play(2, show=show, days=4),
        *[play(value, show=show) for value in (None, 0, -1, MAX_TMDB_ID + 1)],
        HistoryPlay(),
        HistoryPlay.model_validate_json('{"movie":{},"show":{}}'),
        HistoryPlay.model_validate_json('{"episode":{"ids":{"tmdb":9}}}'),
    ]
    watches: dict[TitleKey, datetime] = {}
    assert not fold_page(watches, plays, kind, NOW - timedelta(days=3))
    assert watches == {("tv" if show else "movie", 1): NOW}


def test_cap_unique_titles_and_episode_collapse() -> None:
    watches: dict[TitleKey, datetime] = {}
    assert not fold_page(watches, [play(1, show=True), play(1, show=True, days=1)], "episodes")
    assert watches == {("tv", 1): NOW}
    assert fold_page(watches, [play(i, show=True) for i in range(2, 600)], "episodes")
    assert len(watches) == 500 and ("tv", 501) not in watches

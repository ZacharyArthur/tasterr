"""Pure, bounded folding of Trakt plays into canonical latest-watch facts."""

from datetime import UTC, datetime

from tasterr.clients.trakt import HistoryPlay, HistoryType
from tasterr.recommend.signals import MAX_TMDB_ID, TitleKey

TITLE_CAP = 500


def fold_page(
    watches: dict[TitleKey, datetime],
    plays: list[HistoryPlay],
    media_type: HistoryType,
    lower_bound: datetime | None = None,
) -> bool:
    for play in plays:
        title = play.movie if media_type == "movies" else play.show
        tmdb_id = title.ids.tmdb if title is not None else None
        if tmdb_id is None or not 1 <= tmdb_id <= MAX_TMDB_ID or play.watched_at is None:
            continue
        watched_at = play.watched_at
        if watched_at.tzinfo is None:
            continue
        watched_at = watched_at.astimezone(UTC).replace(tzinfo=None)
        if lower_bound is not None and watched_at < lower_bound:
            continue
        key: TitleKey = ("movie" if media_type == "movies" else "tv", tmdb_id)
        if key not in watches or watched_at > watches[key]:
            watches[key] = watched_at
        if len(watches) >= TITLE_CAP:
            return True
    return False

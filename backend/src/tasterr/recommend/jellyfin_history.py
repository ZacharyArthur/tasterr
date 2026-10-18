"""Bounded, transient Jellyfin history mapping into canonical latest-watch facts."""

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from tasterr.clients.jellyfin import JELLYFIN_PAGE_SIZE, JellyfinClient, JellyfinItem
from tasterr.recommend.signals import MAX_TMDB_ID, TitleKey

HISTORY_DEADLINE_SECONDS = 30.0
HISTORY_MAX_PER_TYPE = 500


@dataclass(frozen=True)
class JellyfinHistoryResult:
    watches: dict[TitleKey, datetime]
    complete: bool


def _tmdb_id(item: JellyfinItem) -> int | None:
    raw = item.provider_ids.get("Tmdb", "")
    if not raw.isascii() or not raw.isdecimal() or len(raw) > 10:
        return None
    value = int(raw)
    return value if 0 < value <= MAX_TMDB_ID else None


async def read_history(
    client: JellyfinClient, user_id: str, start: datetime, cutoff: datetime
) -> JellyfinHistoryResult:
    watches: dict[TitleKey, datetime] = {}
    series_plays: dict[str, datetime] = {}
    complete = True
    try:
        async with asyncio.timeout(HISTORY_DEADLINE_SECONDS):
            for item_type in ("Movie", "Episode"):
                kind: Literal["Movie", "Episode"] = item_type
                previous_played: datetime | None = None
                ordered = True
                for offset in range(0, HISTORY_MAX_PER_TYPE, JELLYFIN_PAGE_SIZE):
                    page = await client.played_items(user_id, kind, offset)
                    reached_start = False
                    for item in page.items:
                        if item.user_data is None or item.user_data.last_played_date is None:
                            continue
                        played = item.user_data.last_played_date
                        if played.tzinfo is not None:
                            played = played.astimezone(UTC).replace(tzinfo=None)
                        if previous_played is not None and played > previous_played:
                            ordered = False
                            complete = False
                        previous_played = played
                        if played < start:
                            reached_start = True
                            continue
                        if played > cutoff:
                            continue
                        if kind == "Episode":
                            if item.series_id is not None:
                                series_plays[item.series_id] = max(
                                    series_plays.get(item.series_id, played), played
                                )
                        elif (tmdb_id := _tmdb_id(item)) is not None:
                            key: TitleKey = ("movie", tmdb_id)
                            watches[key] = max(watches.get(key, played), played)
                    if (
                        (reached_start and ordered)
                        or len(page.items) < JELLYFIN_PAGE_SIZE
                        or offset + len(page.items) >= page.total_record_count
                    ):
                        break
            ids = list(series_plays)
            for offset in range(0, len(ids), JELLYFIN_PAGE_SIZE):
                batch = ids[offset : offset + JELLYFIN_PAGE_SIZE]
                page = await client.series(user_id, batch)
                for item in page.items:
                    if item.id not in batch or (tmdb_id := _tmdb_id(item)) is None:
                        continue
                    played = series_plays[item.id]
                    key = ("tv", tmdb_id)
                    watches[key] = max(watches.get(key, played), played)
    except TimeoutError:
        complete = False
    return JellyfinHistoryResult(watches, complete)

"""Live Jellyfin resume mapping; only canonical candidates leave this module."""

import asyncio
from datetime import UTC

from tasterr.catalog.jellyfin_ids import tmdb_id
from tasterr.catalog.models import MediaType
from tasterr.catalog.resume import ResumeCandidate
from tasterr.clients.jellyfin import JellyfinClient, JellyfinItem


def _played(item: JellyfinItem) -> float | None:
    played = item.user_data.last_played_date if item.user_data else None
    if played is None:
        return None
    return played.replace(tzinfo=UTC).timestamp() if played.tzinfo is None else played.timestamp()


async def resume_candidates(client: JellyfinClient, user_id: str) -> list[ResumeCandidate]:
    pages = await asyncio.gather(
        client.resume_items(user_id),
        client.next_up(user_id),
        client.played_items(user_id, "Episode", 0),
        return_exceptions=True,
    )
    resume, next_up, recent = pages
    if isinstance(resume, BaseException):
        raise resume
    if isinstance(next_up, BaseException):
        raise next_up
    if isinstance(recent, BaseException):
        raise recent
    activity: dict[str, float] = {}
    for item in recent.items:
        played = _played(item)
        if item.type == "Episode" and item.series_id is not None and played is not None:
            activity[item.series_id] = max(activity.get(item.series_id, played), played)
    ids = list(
        dict.fromkeys(
            item.series_id
            for item in [*resume.items, *next_up.items]
            if item.type == "Episode" and item.series_id is not None
        )
    )
    series: dict[str, JellyfinItem] = {}
    if ids:
        series = {
            item.id: item for item in (await client.series(user_id, ids)).items if item.id in ids
        }
    candidates: list[ResumeCandidate] = []
    for is_next_up, items in ((False, resume.items), (True, next_up.items)):
        for position, item in enumerate(items):
            context = None
            timestamp = _played(item)
            if item.type == "Movie" and not is_next_up:
                canonical_id = tmdb_id(item)
                media_type: MediaType = "movie"
            elif item.type == "Episode":
                season, episode = item.parent_index_number, item.index_number
                if (
                    season is None
                    or episode is None
                    or season < 0
                    or episode < 0
                    or item.series_id is None
                ):
                    continue
                show = series.get(item.series_id)
                canonical_id = tmdb_id(show) if show else None
                media_type = "tv"
                context = f"S{season} E{episode}"
                if is_next_up:
                    timestamp = activity.get(item.series_id)
                    if timestamp is None:
                        timestamp = _played(show) if show else None
                    if timestamp is None:
                        timestamp = -(position + 1)
            else:
                continue
            if canonical_id is None or timestamp is None:
                continue
            progress = None
            if not is_next_up:
                offset = item.user_data.playback_position_ticks if item.user_data else None
                runtime = item.run_time_ticks
                if offset is None or runtime is None or offset < 0 or runtime <= 0:
                    continue
                progress = 100 * offset // runtime
                if not 1 <= progress <= 99:
                    continue
            candidates.append(
                ResumeCandidate(media_type, canonical_id, timestamp, (1, 0), progress, context)
            )
    return candidates

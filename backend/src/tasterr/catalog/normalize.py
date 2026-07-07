"""Pure TMDB-wire → domain normalization. No network, no settings, no I/O.

TMDB text and identifiers are untrusted input: the trailer key is charset-checked
before it can shape an embed URL, and unknown wire fields were already dropped by
the client's `extra="ignore"` models.
"""

import re

from tasterr.catalog.models import (
    Genre,
    MediaDetail,
    MediaSummary,
    MediaType,
    Person,
    ProviderInfo,
    SeasonSummary,
    Video,
    WatchProviders,
)
from tasterr.clients.tmdb import (
    TmdbCastMember,
    TmdbCrewMember,
    TmdbDetail,
    TmdbImage,
    TmdbMediaResult,
    TmdbVideo,
    TmdbWatchEntry,
    TmdbWatchProvider,
)

_YOUTUBE_KEY = re.compile(r"[A-Za-z0-9_-]+")
_KEY_CREW_JOBS = ("Director", "Creator", "Writer", "Screenplay", "Executive Producer")
_MAX_CAST = 12
_MAX_CREW = 8


def _parse_year(value: str | None) -> int | None:
    if not value or len(value) < 4:
        return None
    try:
        return int(value[:4])
    except ValueError:
        return None


def resolve_media_type(raw: TmdbMediaResult, fallback: MediaType | None) -> MediaType | None:
    if raw.media_type == "movie":
        return "movie"
    if raw.media_type == "tv":
        return "tv"
    if raw.media_type == "person":
        return None
    if fallback is not None:
        return fallback
    if raw.title:
        return "movie"
    if raw.name:
        return "tv"
    return None


def to_summary(raw: TmdbMediaResult, fallback: MediaType | None) -> MediaSummary | None:
    media_type = resolve_media_type(raw, fallback)
    if media_type is None:
        return None
    title = raw.title or raw.name or raw.original_title or raw.original_name or "Untitled"
    return MediaSummary(
        id=raw.id,
        media_type=media_type,
        title=title,
        overview=raw.overview or "",
        poster_path=raw.poster_path,
        backdrop_path=raw.backdrop_path,
        year=_parse_year(raw.release_date or raw.first_air_date),
        vote_average=raw.vote_average,
    )


def to_summaries(results: list[TmdbMediaResult], fallback: MediaType | None) -> list[MediaSummary]:
    out: list[MediaSummary] = []
    for raw in results:
        summary = to_summary(raw, fallback)
        if summary is not None:
            out.append(summary)
    return out


def pick_trailer(videos: list[TmdbVideo]) -> Video | None:
    youtube = [v for v in videos if v.site == "YouTube" and v.key and _YOUTUBE_KEY.fullmatch(v.key)]
    if not youtube:
        return None

    def rank(video: TmdbVideo) -> int:
        score = 0
        if video.type == "Trailer":
            score += 4
        elif video.type == "Teaser":
            score += 2
        if video.official:
            score += 1
        return score

    best = max(youtube, key=rank)
    return Video(
        key=best.key, site=best.site, type=best.type, name=best.name, official=best.official
    )


def pick_logo(logos: list[TmdbImage]) -> str | None:
    if not logos:
        return None

    def score(image: TmdbImage) -> float:
        value = image.vote_average
        if image.iso_639_1 == "en":
            value += 50.0
        elif image.iso_639_1 is None:
            value += 10.0
        return value

    return max(logos, key=score).file_path or None


def _cast(members: list[TmdbCastMember]) -> list[Person]:
    ordered = sorted(members, key=lambda m: m.order if m.order is not None else 999)
    return [
        Person(id=m.id, name=m.name, role=m.character or "", profile_path=m.profile_path)
        for m in ordered[:_MAX_CAST]
    ]


def _key_crew(members: list[TmdbCrewMember]) -> list[Person]:
    seen: set[int] = set()
    out: list[Person] = []
    for member in members:
        if member.job not in _KEY_CREW_JOBS or member.id in seen:
            continue
        seen.add(member.id)
        out.append(
            Person(
                id=member.id,
                name=member.name,
                role=member.job or "",
                profile_path=member.profile_path,
            )
        )
        if len(out) >= _MAX_CREW:
            break
    return out


def _certification(raw: TmdbDetail, region: str, media: MediaType) -> str | None:
    if media == "movie":
        if raw.release_dates is None:
            return None
        entry = next((e for e in raw.release_dates.results if e.iso_3166_1 == region), None)
        if entry is None:
            return None
        return next((d.certification for d in entry.release_dates if d.certification), None)
    if raw.content_ratings is None:
        return None
    rating = next((e.rating for e in raw.content_ratings.results if e.iso_3166_1 == region), None)
    return rating or None


def _seasons(raw: TmdbDetail) -> list[SeasonSummary]:
    return [
        SeasonSummary(
            season_number=s.season_number,
            name=s.name,
            episode_count=s.episode_count,
            air_date=s.air_date,
        )
        for s in raw.seasons
        if s.season_number >= 1
    ]


def _providers(items: list[TmdbWatchProvider]) -> list[ProviderInfo]:
    ordered = sorted(items, key=lambda p: p.display_priority)
    return [
        ProviderInfo(provider_id=p.provider_id, name=p.provider_name, logo_path=p.logo_path)
        for p in ordered
    ]


def _watch(raw: TmdbDetail, region: str) -> WatchProviders:
    entry: TmdbWatchEntry | None = None
    if raw.watch_providers is not None:
        entry = raw.watch_providers.results.get(region)
    if entry is None:
        return WatchProviders()
    return WatchProviders(
        flatrate=_providers(entry.flatrate),
        rent=_providers(entry.rent),
        buy=_providers(entry.buy),
        free=_providers(entry.free),
    )


def to_detail(raw: TmdbDetail, media: MediaType, region: str) -> MediaDetail:
    title = raw.title or raw.name or raw.original_title or raw.original_name or "Untitled"
    runtime = (
        raw.runtime
        if media == "movie"
        else (raw.episode_run_time[0] if raw.episode_run_time else None)
    )
    videos = raw.videos.results if raw.videos else []
    logos = raw.images.logos if raw.images else []
    cast = raw.credits.cast if raw.credits else []
    crew = raw.credits.crew if raw.credits else []
    recommendations = raw.recommendations.results if raw.recommendations else []
    similar = raw.similar.results if raw.similar else []
    return MediaDetail(
        id=raw.id,
        media_type=media,
        title=title,
        overview=raw.overview or "",
        poster_path=raw.poster_path,
        backdrop_path=raw.backdrop_path,
        year=_parse_year(raw.release_date or raw.first_air_date),
        vote_average=raw.vote_average,
        tagline=raw.tagline or "",
        genres=[Genre(id=g.id, name=g.name) for g in raw.genres],
        runtime=runtime,
        release_date=raw.release_date or raw.first_air_date,
        certification=_certification(raw, region, media),
        logo_path=pick_logo(logos),
        trailer=pick_trailer(videos),
        cast=_cast(cast),
        crew=_key_crew(crew),
        watch=_watch(raw, region),
        recommendations=to_summaries(recommendations, None),
        similar=to_summaries(similar, None),
        seasons=_seasons(raw),
        number_of_seasons=raw.number_of_seasons,
    )

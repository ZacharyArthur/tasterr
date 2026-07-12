"""Title facts: the feature-oriented view of a TMDB detail (M4 taste engine).

Internal domain data for `recommend/` — never part of an API response model
(regression-tested against the OpenAPI schema) and, like every catalog module,
settings-free. Facts derive from the same cached detail payload as the
normalized `MediaDetail`, so a warm detail cache serves facts for free.
"""

from pydantic import BaseModel

from tasterr.catalog.models import MediaType
from tasterr.catalog.normalize import parse_year
from tasterr.clients.tmdb import TmdbDetail

_MAX_FACT_CAST = 5
_MAX_CREATORS = 3


class TitleFacts(BaseModel):
    tmdb_id: int
    media_type: MediaType
    title: str
    genres: list[str] = []
    keywords: list[str] = []
    cast: list[str] = []
    creators: list[str] = []  # movie directors / TV created-by
    original_language: str = ""
    year: int | None = None
    runtime: int | None = None
    vote_average: float = 0.0
    vote_count: int = 0


def to_facts(raw: TmdbDetail, media: MediaType) -> TitleFacts:
    title = raw.title or raw.name or raw.original_title or raw.original_name or "Untitled"
    keywords = [k.name for k in raw.keywords.all if k.name] if raw.keywords else []
    cast_members = raw.credits.cast if raw.credits else []
    ordered_cast = sorted(cast_members, key=lambda m: m.order if m.order is not None else 999)
    if media == "movie":
        crew = raw.credits.crew if raw.credits else []
        creators = [m.name for m in crew if m.job == "Director" and m.name]
    else:
        creators = [c.name for c in raw.created_by if c.name]
    runtime = (
        raw.runtime
        if media == "movie"
        else (raw.episode_run_time[0] if raw.episode_run_time else None)
    )
    return TitleFacts(
        tmdb_id=raw.id,
        media_type=media,
        title=title,
        genres=[g.name for g in raw.genres if g.name],
        keywords=keywords,
        cast=[m.name for m in ordered_cast[:_MAX_FACT_CAST] if m.name],
        creators=creators[:_MAX_CREATORS],
        original_language=raw.original_language,
        year=parse_year(raw.release_date or raw.first_air_date),
        runtime=runtime,
        vote_average=raw.vote_average,
        vote_count=raw.vote_count,
    )

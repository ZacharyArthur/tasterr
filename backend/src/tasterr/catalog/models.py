"""Typed, secret-free domain models — the shapes served toward the client.

These modules MUST NOT import application settings (import-linter-enforced): a
client-facing model can carry no secret configuration.
"""

from typing import Literal

from pydantic import BaseModel

from tasterr.catalog.availability import Availability

MediaType = Literal["movie", "tv"]
RailKind = Literal["standard", "genre", "top10"]


class MediaSummary(BaseModel):
    id: int
    media_type: MediaType
    title: str
    overview: str
    poster_path: str | None
    backdrop_path: str | None
    year: int | None
    vote_average: float


class Genre(BaseModel):
    id: int
    name: str


class Person(BaseModel):
    id: int
    name: str
    role: str
    profile_path: str | None


class Video(BaseModel):
    key: str
    site: str
    type: str
    name: str
    official: bool


class SeasonSummary(BaseModel):
    season_number: int
    name: str
    episode_count: int
    air_date: str | None


class ProviderInfo(BaseModel):
    provider_id: int
    name: str
    logo_path: str | None


class WatchProviders(BaseModel):
    flatrate: list[ProviderInfo] = []
    rent: list[ProviderInfo] = []
    buy: list[ProviderInfo] = []
    free: list[ProviderInfo] = []


class TasteFlags(BaseModel):
    """The caller's own toggle state for a title — resolved from their signals
    at read time so the detail modal renders current watchlist/hidden state."""

    watchlisted: bool = False
    hidden: bool = False


class MediaDetail(MediaSummary):
    tagline: str
    genres: list[Genre] = []
    runtime: int | None
    release_date: str | None
    certification: str | None
    logo_path: str | None
    trailer: Video | None
    cast: list[Person] = []
    crew: list[Person] = []
    watch: WatchProviders
    recommendations: list[MediaSummary] = []
    similar: list[MediaSummary] = []
    seasons: list[SeasonSummary] = []
    number_of_seasons: int | None
    # Populated by the title endpoint (M3); None until then and on the normalizer's
    # own output, which is TMDB-only. Seerr-down leaves it Unknown, never absent.
    availability: Availability | None = None
    # Populated by the title endpoint (M4) from the caller's own signals;
    # None on the normalizer's TMDB-only output.
    taste: TasteFlags | None = None


class HeroSlide(BaseModel):
    item: MediaSummary
    logo_path: str | None
    trailer: Video | None
    certification: str | None
    runtime: int | None
    genres: list[str] = []


class Rail(BaseModel):
    id: str
    title: str
    kind: RailKind = "standard"
    items: list[MediaSummary] = []


class HomeFeed(BaseModel):
    hero: list[HeroSlide] = []
    rails: list[Rail] = []


class RailsPage(BaseModel):
    rails: list[Rail] = []
    next_cursor: int | None = None


class SearchResponse(BaseModel):
    results: list[MediaSummary] = []

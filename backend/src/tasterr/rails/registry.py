"""Rail provider interface and the non-personalized provider sets (SPEC §7).

A provider is metadata (id/title/kind) plus an async `fetch(ctx) -> items`. The
composer wraps items into a `Rail` (applying cross-rail de-dupe and a minimum
size). This is the seam M4 extends with personalized providers and M5 gates with
admin toggles; M2 wires every provider on and threads no user into scoring.
"""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import date

from tasterr.catalog.models import MediaSummary, MediaType, RailKind
from tasterr.catalog.service import CatalogService

MIN_RAIL_ITEMS = 4
HERO_SIZE = 5
HOME_GENRE_COUNT = 4
EXTRA_PAGE_SIZE = 4
HERO_GENRE_LABELS = 3

# Curated, ordered genre labels surfaced first (rest flow into infinite scroll).
GENRE_PICKS = (
    "Action",
    "Comedy",
    "Drama",
    "Science Fiction",
    "Thriller",
    "Animation",
    "Horror",
    "Romance",
    "Adventure",
    "Mystery",
    "Fantasy",
    "Family",
)
DECADES = (2020, 2010, 2000, 1990, 1980)
_GENRE_MIN_VOTES = {"movie": 50, "tv": 30}


@dataclass
class RailContext:
    catalog: CatalogService


@dataclass
class RailProvider:
    id: str
    title: str
    kind: RailKind
    fetch: Callable[[RailContext], Awaitable[list[MediaSummary]]]


def _today() -> str:
    return date.today().isoformat()


def home_providers() -> list[RailProvider]:
    return [
        RailProvider("trending", "Trending Now", "standard", lambda ctx: ctx.catalog.trending()),
        # Not region-scoped in M2: TMDB watch_region is inert without a provider
        # filter, which needs admin service selection (M5). Labelled honestly until
        # then; true "top in region" lands with M5.
        RailProvider(
            "popular",
            "Popular Movies",
            "standard",
            lambda ctx: ctx.catalog.discover("movie", sort_by="popularity.desc", min_votes=50),
        ),
        RailProvider(
            "recently-added",
            "Recently Added",
            "standard",
            lambda ctx: ctx.catalog.discover(
                "movie",
                sort_by="primary_release_date.desc",
                release_lte=_today(),
                min_votes=5,
            ),
        ),
    ]


def top_rated_providers() -> list[RailProvider]:
    return [
        RailProvider(
            "top-rated-movie",
            "Top Rated Movies",
            "standard",
            lambda ctx: ctx.catalog.discover("movie", sort_by="vote_average.desc", min_votes=500),
        ),
        RailProvider(
            "top-rated-tv",
            "Top Rated Shows",
            "standard",
            lambda ctx: ctx.catalog.discover("tv", sort_by="vote_average.desc", min_votes=300),
        ),
    ]


def genre_provider(genre_id: int, name: str, media: MediaType) -> RailProvider:
    async def fetch(ctx: RailContext) -> list[MediaSummary]:
        return await ctx.catalog.discover(
            media, genres=[genre_id], min_votes=_GENRE_MIN_VOTES[media]
        )

    label = name if media == "movie" else f"{name} · TV"
    return RailProvider(f"genre-{media}-{genre_id}", label, "genre", fetch)


def decade_provider(decade: int) -> RailProvider:
    async def fetch(ctx: RailContext) -> list[MediaSummary]:
        return await ctx.catalog.discover(
            "movie",
            sort_by="popularity.desc",
            release_gte=f"{decade}-01-01",
            release_lte=f"{decade + 9}-12-31",
            min_votes=100,
        )

    return RailProvider(f"decade-{decade}", f"{decade}s", "standard", fetch)

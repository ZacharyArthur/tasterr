"""Rail provider interface and the provider sets (SPEC §7).

A provider is metadata (id/title/kind) plus an async `fetch(ctx) -> items`. The
composer wraps items into a `Rail` (applying cross-rail de-dupe and a per-
provider minimum size). M4 threads the authed user + taste service through the
context and adds the personalized providers; M5 gates providers with admin
toggles. The personalized fetches swallow *any* engine failure to an empty
rail — personalization degrades, it never blocks browsing.
"""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from itertools import zip_longest

from pydantic import SecretStr

from tasterr.catalog.models import MediaSummary, MediaType, RailKind, ServiceOption
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError
from tasterr.db.models import User
from tasterr.recommend.service import TasteService
from tasterr.runtime_settings import RailType

logger = logging.getLogger("tasterr.rails")

MIN_RAIL_ITEMS = 4
# A one-title watchlist is still the user's list — never omit it as "thin".
MY_LIST_MIN_ITEMS = 1
HERO_SIZE = 5
EXTRA_PAGE_SIZE = 4
HERO_GENRE_LABELS = 3
SERVICE_RAIL_LIMIT = 4
SERVICE_RAIL_SIZE = 20

DECADES = (2020, 2010, 2000, 1990, 1980)
_GENRE_MIN_VOTES = {"movie": 50, "tv": 30}


@dataclass
class RailContext:
    catalog: CatalogService
    user: User | None = None  # None → non-personalized compose (extra pages, tests)
    taste: TasteService | None = None
    plex: PlexCatalogService | None = None
    plex_account_token: SecretStr | None = None
    disabled_rail_types: frozenset[RailType] = frozenset()

    def enabled(self, rail_type: RailType) -> bool:
        return rail_type not in self.disabled_rail_types


@dataclass
class RailProvider:
    id: str
    title: str
    kind: RailKind
    fetch: Callable[[RailContext], Awaitable[list[MediaSummary]]]
    rail_type: RailType
    min_items: int = field(default=MIN_RAIL_ITEMS)
    # Exclusive providers share the request's AsyncSession, which is not safe
    # for concurrent tasks — the composer runs them one at a time instead of
    # inside the gather (review finding: concurrent vector/profile writes
    # collided and silently dropped the personalized rails).
    exclusive: bool = field(default=False)


def _today() -> str:
    return date.today().isoformat()


def _days_ago(days: int) -> str:
    return (date.today() - timedelta(days=days)).isoformat()


def personalized_home_providers(
    ctx: RailContext,
) -> tuple[list[RailProvider], list[RailProvider]]:
    """The M4 providers as (before trending, after trending) — empty for a
    user-less context, and empty rails (omitted by the composer) when the
    user has no signals, which *is* the non-personalized fallback."""
    if ctx.user is None or ctx.taste is None:
        return [], []
    taste = ctx.taste
    user_id = ctx.user.id

    async def fetch_my_list(_: RailContext) -> list[MediaSummary]:
        return await _engine_safe(taste, taste.my_list(user_id), "my-list", user_id)

    async def fetch_recommended(_: RailContext) -> list[MediaSummary]:
        return await _engine_safe(
            taste, taste.recommended_for_you(user_id), "recommended-for-you", user_id
        )

    async def fetch_more_like(_: RailContext) -> list[MediaSummary]:
        try:
            result = await taste.more_like(user_id)
        except Exception:  # engine failure → no rail, never a failed home
            logger.error("rails: more-like failed")
            await _quiet_rollback(taste)
            return []
        if result is None:
            return []
        source_title, is_plex_watch, items = result
        prefix = "Because You Watched" if is_plex_watch else "More Like"
        more_like.title = f"{prefix} {source_title}"  # resolved with the fetch
        return items

    my_list = RailProvider(
        "my-list",
        "My List",
        "standard",
        fetch_my_list,
        RailType.MY_LIST,
        min_items=MY_LIST_MIN_ITEMS,
        exclusive=True,
    )
    recommended = RailProvider(
        "recommended-for-you",
        "Recommended for You",
        "standard",
        fetch_recommended,
        RailType.RECOMMENDED,
        exclusive=True,
    )
    more_like = RailProvider(
        "more-like",
        "More like",
        "standard",
        fetch_more_like,
        RailType.MORE_LIKE,
        exclusive=True,
    )
    return [my_list, recommended], [more_like]


def continue_watching_provider(ctx: RailContext) -> RailProvider | None:
    """Caller-scoped live Plex provider; no request DB session is involved."""
    if ctx.user is None or ctx.plex is None or ctx.plex_account_token is None:
        return None
    plex = ctx.plex
    user_id = ctx.user.id
    account_token = ctx.plex_account_token

    async def fetch(_: RailContext) -> list[MediaSummary]:
        return await plex.continue_watching(user_id, account_token.get_secret_value())

    return RailProvider(
        "continue-watching",
        "Continue Watching",
        "standard",
        fetch,
        RailType.CONTINUE_WATCHING,
    )


def unexpected_picks_provider(ctx: RailContext) -> RailProvider | None:
    if ctx.user is None or ctx.taste is None:
        return None
    taste = ctx.taste
    user_id = ctx.user.id

    async def fetch(_: RailContext) -> list[MediaSummary]:
        return await _engine_safe(
            taste, taste.unexpected_picks(user_id), "unexpected-picks", user_id
        )

    return RailProvider(
        "unexpected-picks",
        "Picks You Wouldn't Usually Watch",
        "standard",
        fetch,
        RailType.UNEXPECTED_PICKS,
        exclusive=True,
    )


async def _engine_safe(
    taste: TasteService, call: Awaitable[list[MediaSummary]], rail_id: str, user_id: int
) -> list[MediaSummary]:
    try:
        return await call
    except Exception:  # engine failure → no rail, never a failed home
        logger.error("rails: %s failed", rail_id)
        await _quiet_rollback(taste)
        return []


async def _quiet_rollback(taste: TasteService) -> None:
    """A failed flush leaves the shared session rollback-only; repair it so
    later providers and the request's final commit aren't poisoned."""
    try:
        await taste.rollback()
    except Exception:
        logger.error("rails: session rollback after degrade failed")


def home_providers() -> list[RailProvider]:
    return [
        RailProvider(
            "trending",
            "Trending Now",
            "standard",
            lambda ctx: ctx.catalog.trending(),
            RailType.TRENDING,
        ),
        # Not region-scoped in M2: TMDB watch_region is inert without a provider
        # filter, which needs admin service selection (M5). Labelled honestly until
        # then; true "top in region" lands with M5.
        RailProvider(
            "popular",
            "Popular Movies",
            "standard",
            lambda ctx: ctx.catalog.discover("movie", sort_by="popularity.desc", min_votes=50),
            RailType.POPULAR,
        ),
        RailProvider(
            "popular-tv",
            "Popular TV",
            "standard",
            lambda ctx: ctx.catalog.discover("tv", sort_by="popularity.desc", min_votes=30),
            RailType.POPULAR,
        ),
        RailProvider(
            "recently-added",
            "Recent Releases",
            "standard",
            lambda ctx: ctx.catalog.discover(
                "movie",
                sort_by="primary_release_date.desc",
                release_lte=_today(),
                min_votes=5,
            ),
            RailType.RECENT,
        ),
    ]


def top_rated_providers() -> list[RailProvider]:
    return [
        RailProvider(
            "top-rated-movie",
            "Top Rated Movies",
            "standard",
            lambda ctx: ctx.catalog.discover("movie", sort_by="vote_average.desc", min_votes=500),
            RailType.TOP_RATED,
        ),
        RailProvider(
            "top-rated-tv",
            "Top Rated TV",
            "standard",
            lambda ctx: ctx.catalog.discover("tv", sort_by="vote_average.desc", min_votes=300),
            RailType.TOP_RATED,
        ),
    ]


def genre_provider(genre_id: int, name: str, media: MediaType) -> RailProvider:
    async def fetch(ctx: RailContext) -> list[MediaSummary]:
        return await ctx.catalog.discover(
            media, genres=[genre_id], min_votes=_GENRE_MIN_VOTES[media]
        )

    label = f"{name} · {'Movies' if media == 'movie' else 'TV'}"
    return RailProvider(f"genre-{media}-{genre_id}", label, "genre", fetch, RailType.GENRES)


def decade_provider(decade: int) -> RailProvider:
    async def fetch(ctx: RailContext) -> list[MediaSummary]:
        return await ctx.catalog.discover(
            "movie",
            sort_by="popularity.desc",
            release_gte=f"{decade}-01-01",
            release_lte=f"{decade + 9}-12-31",
            min_votes=100,
        )

    return RailProvider(f"decade-{decade}", f"{decade}s", "standard", fetch, RailType.DECADES)


def service_provider(service: ServiceOption) -> RailProvider:
    async def discover(ctx: RailContext, media: MediaType, sort_by: str) -> list[MediaSummary]:
        try:
            return await ctx.catalog.discover(
                media,
                sort_by=sort_by,
                release_gte=_days_ago(365),
                release_lte=_today(),
                min_votes=3,
                service_ids=[service.provider_id],
            )
        except UpstreamError:
            return []

    async def fetch(ctx: RailContext) -> list[MediaSummary]:
        movies, tv = await asyncio.gather(
            discover(ctx, "movie", "primary_release_date.desc"),
            discover(ctx, "tv", "first_air_date.desc"),
        )
        return _interleave(movies, tv)

    return RailProvider(
        f"service-{service.provider_id}",
        f"Recent Releases on {service.name}",
        "standard",
        fetch,
        RailType.SERVICES,
        min_items=SERVICE_RAIL_SIZE // 2,
    )


def _interleave(movies: list[MediaSummary], tv: list[MediaSummary]) -> list[MediaSummary]:
    return [item for pair in zip_longest(movies, tv) for item in pair if item is not None][
        :SERVICE_RAIL_SIZE
    ]

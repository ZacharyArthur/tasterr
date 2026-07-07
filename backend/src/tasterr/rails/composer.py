"""Compose providers into the home feed and the paginated infinite-scroll rails.

Each provider fetch degrades independently (an error yields no rail, never a
failed request); titles are de-duped across the rails of one response; rails
below the minimum size are dropped. A home feed with no rails at all means the
catalog is effectively down — surfaced as an upstream failure (→ 502).
"""

import asyncio

from tasterr.catalog.models import HeroSlide, HomeFeed, MediaSummary, MediaType, Rail, RailsPage
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError, UpstreamUnavailable
from tasterr.rails.registry import (
    DECADES,
    EXTRA_PAGE_SIZE,
    GENRE_PICKS,
    HERO_GENRE_LABELS,
    HERO_SIZE,
    HOME_GENRE_COUNT,
    MIN_RAIL_ITEMS,
    RailContext,
    RailProvider,
    decade_provider,
    genre_provider,
    home_providers,
    top_rated_providers,
)

TitleKey = tuple[MediaType, int]


async def build_home(ctx: RailContext) -> HomeFeed:
    genre_map = await _safe_genre_map(ctx.catalog, "movie")
    providers = home_providers() + _home_genre_providers(genre_map)
    rails = await _compose_rails(ctx, providers)
    if not rails:
        raise UpstreamUnavailable("home feed unavailable")
    hero = await _build_hero(ctx, _hero_pool(rails))
    return HomeFeed(hero=hero, rails=rails)


async def build_extra_rails(ctx: RailContext, cursor: int) -> RailsPage:
    providers = await _extended_providers(ctx.catalog)
    start = max(cursor, 0)
    page = providers[start : start + EXTRA_PAGE_SIZE]
    rails = await _compose_rails(ctx, page)
    end = start + EXTRA_PAGE_SIZE
    return RailsPage(rails=rails, next_cursor=end if end < len(providers) else None)


async def _compose_rails(ctx: RailContext, providers: list[RailProvider]) -> list[Rail]:
    fetched = await asyncio.gather(*(_safe_fetch(provider, ctx) for provider in providers))
    seen: set[TitleKey] = set()
    rails: list[Rail] = []
    for provider, items in zip(providers, fetched, strict=True):
        picked = _dedupe(items, seen)
        if len(picked) >= MIN_RAIL_ITEMS:
            seen.update((item.media_type, item.id) for item in picked)
            rails.append(
                Rail(id=provider.id, title=provider.title, kind=provider.kind, items=picked)
            )
    return rails


def _dedupe(items: list[MediaSummary], seen: set[TitleKey]) -> list[MediaSummary]:
    local: set[TitleKey] = set()
    out: list[MediaSummary] = []
    for item in items:
        key = (item.media_type, item.id)
        if key in seen or key in local:
            continue
        local.add(key)
        out.append(item)
    return out


async def _safe_fetch(provider: RailProvider, ctx: RailContext) -> list[MediaSummary]:
    try:
        return await provider.fetch(ctx)
    except UpstreamError:
        return []  # one dead source drops its rail, never the whole feed


def _hero_pool(rails: list[Rail]) -> list[MediaSummary]:
    for rail in rails:
        if rail.id == "trending":
            return rail.items
    return rails[0].items if rails else []


async def _build_hero(ctx: RailContext, pool: list[MediaSummary]) -> list[HeroSlide]:
    candidates = [s for s in pool if s.backdrop_path][:HERO_SIZE]
    return list(await asyncio.gather(*(_hero_slide(ctx, s) for s in candidates)))


async def _hero_slide(ctx: RailContext, summary: MediaSummary) -> HeroSlide:
    try:
        detail = await ctx.catalog.detail(summary.media_type, summary.id)
    except UpstreamError:
        return HeroSlide(
            item=summary, logo_path=None, trailer=None, certification=None, runtime=None
        )
    return HeroSlide(
        item=summary,
        logo_path=detail.logo_path,
        trailer=detail.trailer,
        certification=detail.certification,
        runtime=detail.runtime,
        genres=[g.name for g in detail.genres][:HERO_GENRE_LABELS],
    )


def _home_genre_providers(genre_map: dict[str, int]) -> list[RailProvider]:
    providers: list[RailProvider] = []
    for name in GENRE_PICKS:
        genre_id = genre_map.get(name)
        if genre_id is not None:
            providers.append(genre_provider(genre_id, name, "movie"))
        if len(providers) >= HOME_GENRE_COUNT:
            break
    return providers


async def _extended_providers(catalog: CatalogService) -> list[RailProvider]:
    movie_map, tv_map = await asyncio.gather(
        _safe_genre_map(catalog, "movie"), _safe_genre_map(catalog, "tv")
    )
    providers: list[RailProvider] = list(top_rated_providers())
    providers += [decade_provider(decade) for decade in DECADES]
    featured = set(GENRE_PICKS)
    providers += [
        genre_provider(gid, name, "movie")
        for name, gid in movie_map.items()
        if name not in featured
    ]
    providers += [genre_provider(gid, name, "tv") for name, gid in tv_map.items()]
    return providers


async def _safe_genre_map(catalog: CatalogService, media: MediaType) -> dict[str, int]:
    try:
        return await catalog.genre_map(media)
    except UpstreamError:
        return {}

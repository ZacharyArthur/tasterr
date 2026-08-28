"""Compose providers into the home feed and the paginated infinite-scroll rails.

Each provider fetch degrades independently (an error yields no rail, never a
failed request); initial Home titles are de-duped across rails, while paginated
category rails de-dupe only internally; rails below the minimum size are dropped.
A home feed with no rails at all means the catalog is effectively down — surfaced
as an upstream failure (→ 502).
"""

import asyncio
from datetime import date
from random import Random

from tasterr.catalog.models import (
    HeroSlide,
    HomeFeed,
    MediaSummary,
    MediaType,
    Rail,
    RailsPage,
    ServiceOption,
)
from tasterr.catalog.service import CatalogService
from tasterr.clients.errors import UpstreamError, UpstreamUnavailable
from tasterr.rails.registry import (
    DECADES,
    EXTRA_PAGE_SIZE,
    HERO_GENRE_LABELS,
    HERO_SIZE,
    SERVICE_RAIL_LIMIT,
    RailContext,
    RailProvider,
    continue_watching_provider,
    decade_provider,
    genre_provider,
    home_providers,
    personalized_home_providers,
    service_provider,
    top_rated_providers,
    unexpected_picks_provider,
)
from tasterr.runtime_settings import RailType

TitleKey = tuple[MediaType, int]


async def build_home(ctx: RailContext) -> HomeFeed:
    # Personalized providers yield nothing for a signal-less user, so the feed
    # degrades to the non-personalized set without changing survivor order.
    before_trending, after_trending = personalized_home_providers(ctx)
    continue_watching = continue_watching_provider(ctx)
    unexpected_picks = unexpected_picks_provider(ctx)
    trending, popular_movies, popular_tv, recent = home_providers()
    providers = [
        *([continue_watching] if continue_watching is not None else []),
        *before_trending,
        trending,
        *after_trending,
        popular_movies,
        popular_tv,
        recent,
        *([unexpected_picks] if unexpected_picks is not None else []),
    ]
    providers = _enabled_providers(ctx, providers)
    rails = await _compose_rails(ctx, providers)
    if not rails:
        if not providers:
            return HomeFeed()
        raise UpstreamUnavailable("home feed unavailable")
    hero = await _build_hero(ctx, _hero_pool(rails)) if ctx.enabled(RailType.HERO) else []
    return HomeFeed(hero=hero, rails=rails)


async def build_extra_rails(ctx: RailContext, cursor: int) -> RailsPage:
    providers = await _extended_providers(ctx)
    start = max(cursor, 0)
    page = providers[start : start + EXTRA_PAGE_SIZE]
    rails = await _compose_rails(ctx, page, dedupe_across_rails=False)
    end = start + EXTRA_PAGE_SIZE
    return RailsPage(rails=rails, next_cursor=end if end < len(providers) else None)


def _enabled_providers(ctx: RailContext, providers: list[RailProvider]) -> list[RailProvider]:
    return [provider for provider in providers if ctx.enabled(provider.rail_type)]


async def _selected_services(ctx: RailContext) -> list[ServiceOption]:
    selected = ctx.catalog.selected_service_ids
    if not selected:
        return []
    try:
        available = await ctx.catalog.services()
    except UpstreamError:
        return []
    by_id = {service.provider_id: service for service in available}
    return [by_id[service_id] for service_id in selected if service_id in by_id][
        :SERVICE_RAIL_LIMIT
    ]


async def _compose_rails(
    ctx: RailContext,
    providers: list[RailProvider],
    *,
    dedupe_across_rails: bool = True,
) -> list[Rail]:
    fetched = await _fetch_all(ctx, providers)
    seen: set[TitleKey] = set()
    rails: list[Rail] = []
    for provider, items in zip(providers, fetched, strict=True):
        picked = _dedupe(items, seen if dedupe_across_rails else set())
        if len(picked) >= provider.min_items:
            if dedupe_across_rails:
                seen.update((item.media_type, item.id) for item in picked)
            rails.append(
                Rail(id=provider.id, title=provider.title, kind=provider.kind, items=picked)
            )
    return rails


async def _fetch_all(ctx: RailContext, providers: list[RailProvider]) -> list[list[MediaSummary]]:
    """Fetch every provider, preserving provider order in the result.

    Exclusive providers share the request's AsyncSession (not safe for
    concurrent tasks — concurrent vector/profile writes collided and silently
    dropped the personalized rails), so they run one at a time; everything
    else fans out concurrently as before.
    """
    concurrent = [(i, p) for i, p in enumerate(providers) if not p.exclusive]
    tasks = [asyncio.create_task(_safe_fetch(provider, ctx)) for _, provider in concurrent]
    fetched: list[list[MediaSummary]] = [[] for _ in providers]
    try:
        for index, provider in enumerate(providers):
            if provider.exclusive:
                fetched[index] = await _safe_fetch(provider, ctx)
        results = await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
    for (index, _), items in zip(concurrent, results, strict=True):
        fetched[index] = items
    return fetched


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


async def _extended_providers(ctx: RailContext) -> list[RailProvider]:
    providers: list[RailProvider] = []
    if ctx.enabled(RailType.TOP_RATED):
        providers += top_rated_providers()
    if ctx.enabled(RailType.SERVICES):
        providers += [service_provider(service) for service in await _selected_services(ctx)]
    if ctx.enabled(RailType.DECADES):
        providers += [decade_provider(decade) for decade in DECADES]
    if not ctx.enabled(RailType.GENRES):
        return providers
    movie_map, tv_map = await asyncio.gather(
        _safe_genre_map(ctx.catalog, "movie"), _safe_genre_map(ctx.catalog, "tv")
    )
    genres = [genre_provider(gid, name, "movie") for name, gid in movie_map.items()]
    genres += [genre_provider(gid, name, "tv") for name, gid in tv_map.items()]
    user_id = ctx.user.id if ctx.user is not None else 0
    Random(f"genres:{user_id}:{date.today().isoformat()}").shuffle(genres)
    providers += genres
    return providers


async def _safe_genre_map(catalog: CatalogService, media: MediaType) -> dict[str, int]:
    try:
        return await catalog.genre_map(media)
    except UpstreamError:
        return {}

"""Catalog façade: fetch via the TMDB client, return normalized domain models.

This is the pure-ish layer between `api/`/`rails/` and `clients/` — it holds no
HTTP itself, so rails and endpoints depend on domain shapes, not TMDB wire types.
"""

from tasterr.catalog import facts, normalize
from tasterr.catalog.models import (
    Genre,
    MediaDetail,
    MediaSummary,
    MediaType,
    RegionOption,
    ServiceOption,
)
from tasterr.clients.tmdb import TmdbClient

DEFAULT_REGION = "US"  # M5's settings GUI will make this admin-configurable.
MAX_QUERY_LENGTH = 100


class CatalogService:
    def __init__(
        self,
        client: TmdbClient,
        region: str = DEFAULT_REGION,
        service_ids: list[int] | None = None,
    ) -> None:
        self._client = client
        self._region = region
        self._service_ids = tuple(service_ids or [])

    @property
    def region(self) -> str:
        return self._region

    @property
    def selected_service_ids(self) -> tuple[int, ...]:
        return self._service_ids

    async def trending(self) -> list[MediaSummary]:
        page = await self._client.trending("all", "day")
        return normalize.to_summaries(page.results, None)

    async def discover(
        self,
        media: MediaType,
        *,
        page: int = 1,
        sort_by: str = "popularity.desc",
        genres: list[int] | None = None,
        min_votes: int | None = None,
        release_gte: str | None = None,
        release_lte: str | None = None,
        service_ids: list[int] | None = None,
    ) -> list[MediaSummary]:
        result = await self._client.discover(
            media,
            region=self._region,
            page=page,
            sort_by=sort_by,
            genres=genres,
            min_votes=min_votes,
            release_gte=release_gte,
            release_lte=release_lte,
            providers=service_ids if service_ids is not None else list(self._service_ids) or None,
        )
        return normalize.to_summaries(result.results, media)

    async def search(self, query: str) -> list[MediaSummary]:
        trimmed = query.strip()
        if not trimmed:
            return []  # short-circuit: no upstream call for an empty query
        page = await self._client.multi_search(trimmed[:MAX_QUERY_LENGTH])
        return normalize.to_summaries(page.results, None)

    async def detail(self, media: MediaType, tmdb_id: int) -> MediaDetail:
        raw = await self._client.detail(media, tmdb_id, self._region)
        return normalize.to_detail(raw, media, self._region)

    async def title_facts(self, media: MediaType, tmdb_id: int) -> facts.TitleFacts:
        """Feature-oriented facts for the taste engine — same cached fetch as
        `detail()`, so a warm detail cache serves facts with no TMDB call."""
        raw = await self._client.detail(media, tmdb_id, self._region)
        return facts.to_facts(raw, media, self._region)

    async def genre_map(self, media: MediaType) -> dict[str, int]:
        genres = await self._client.genres(media)
        return {g.name: g.id for g in genres}

    async def genres(self, media: MediaType) -> list[Genre]:
        genres = await self._client.genres(media)
        return [Genre(id=g.id, name=g.name) for g in genres]

    async def regions(self) -> list[RegionOption]:
        return normalize.to_regions(await self._client.regions())

    async def services(self, region: str | None = None) -> list[ServiceOption]:
        active = region or self._region
        movie, tv = (
            await self._client.providers("movie", active),
            await self._client.providers("tv", active),
        )
        return normalize.to_services(movie, tv, active)

    async def probe(self) -> None:
        await self._client.probe()

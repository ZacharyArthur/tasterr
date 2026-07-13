"""TMDB read client (SPEC §6/§10) — the only module that talks to TMDB.

Wire models parse the (untrusted) TMDB JSON with `extra="ignore"`; catalog/
maps them to domain models. Every call is cache-wrapped (TTL + stale-on-error)
and carries a timeout with a bounded, `Retry-After`-honoring backoff on 429/5xx.
The api_key is attached server-side only and never surfaces to a client.
"""

import asyncio
from typing import Literal, TypeVar

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tasterr.cache import Cache, CacheOpts
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable

BASE = "https://api.themoviedb.org/3"
LANGUAGE = "en-US"
TIMEOUT_SECONDS = 10.0
MAX_RETRIES = 2
BACKOFF_BASE_SECONDS = 0.25

MediaType = Literal["movie", "tv"]
# release_dates (movie) / content_ratings (tv) carry the region certification;
# keywords feed the taste engine's feature vectors (M4).
DETAIL_APPEND = (
    "videos,images,credits,recommendations,similar,watch/providers,"
    "release_dates,content_ratings,keywords"
)

TTL_GENRES = CacheOpts(ttl=7 * 24 * 3600, stale=30 * 24 * 3600)
TTL_REGIONS = CacheOpts(ttl=7 * 24 * 3600, stale=30 * 24 * 3600)
TTL_PROVIDERS = CacheOpts(ttl=12 * 3600, stale=3 * 24 * 3600)
TTL_DISCOVER = CacheOpts(ttl=45 * 60, stale=12 * 3600)
TTL_TRENDING = CacheOpts(ttl=30 * 60, stale=6 * 3600)
TTL_DETAIL = CacheOpts(ttl=6 * 3600, stale=2 * 24 * 3600)
TTL_SEARCH = CacheOpts(ttl=5 * 60, stale=5 * 60)


class CatalogNotConfigured(Exception):
    """No TMDB API key configured. The api layer maps this to 503."""


# ── Wire models (raw TMDB shapes) ────────────────────────────────────────────


class TmdbMediaResult(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    media_type: str | None = None
    title: str | None = None
    name: str | None = None
    original_title: str | None = None
    original_name: str | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    release_date: str | None = None
    first_air_date: str | None = None
    vote_average: float = 0.0
    popularity: float = 0.0
    genre_ids: list[int] = []
    original_language: str = ""


class TmdbMediaPage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    page: int = 1
    total_pages: int = 1
    results: list[TmdbMediaResult] = []


class TmdbGenre(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""


class TmdbGenreList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    genres: list[TmdbGenre] = []


class TmdbRegion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iso_3166_1: str
    english_name: str = ""
    native_name: str = ""


class TmdbRegionList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TmdbRegion] = []


class TmdbProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: int
    provider_name: str = ""
    logo_path: str | None = None
    display_priority: int = 9999
    display_priorities: dict[str, int] = {}

    def priority_for(self, region: str) -> int:
        return self.display_priorities.get(region, self.display_priority)


class TmdbProviderList(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TmdbProvider] = []


class TmdbConfiguration(BaseModel):
    model_config = ConfigDict(extra="ignore")

    images: dict[str, object]


class TmdbVideo(BaseModel):
    model_config = ConfigDict(extra="ignore")

    key: str = ""
    site: str = ""
    type: str = ""
    name: str = ""
    official: bool = False


class TmdbImage(BaseModel):
    model_config = ConfigDict(extra="ignore")

    file_path: str = ""
    iso_639_1: str | None = None
    vote_average: float = 0.0


class TmdbCastMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""
    character: str | None = None
    profile_path: str | None = None
    order: int | None = None


class TmdbCrewMember(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""
    job: str | None = None
    profile_path: str | None = None


class TmdbSeason(BaseModel):
    model_config = ConfigDict(extra="ignore")

    season_number: int
    name: str = ""
    episode_count: int = 0
    air_date: str | None = None


class TmdbWatchProvider(BaseModel):
    model_config = ConfigDict(extra="ignore")

    provider_id: int
    provider_name: str = ""
    logo_path: str | None = None
    display_priority: int = 0


class TmdbWatchEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    flatrate: list[TmdbWatchProvider] = []
    rent: list[TmdbWatchProvider] = []
    buy: list[TmdbWatchProvider] = []
    free: list[TmdbWatchProvider] = []
    ads: list[TmdbWatchProvider] = []


class TmdbVideos(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TmdbVideo] = []


class TmdbImages(BaseModel):
    model_config = ConfigDict(extra="ignore")

    logos: list[TmdbImage] = []


class TmdbCredits(BaseModel):
    model_config = ConfigDict(extra="ignore")

    cast: list[TmdbCastMember] = []
    crew: list[TmdbCrewMember] = []


class TmdbWatchProviders(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: dict[str, TmdbWatchEntry] = {}


class TmdbReleaseDateItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    certification: str = ""


class TmdbReleaseDatesEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iso_3166_1: str = ""
    release_dates: list[TmdbReleaseDateItem] = []


class TmdbReleaseDates(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TmdbReleaseDatesEntry] = []


class TmdbContentRatingEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    iso_3166_1: str = ""
    rating: str = ""


class TmdbContentRatings(BaseModel):
    model_config = ConfigDict(extra="ignore")

    results: list[TmdbContentRatingEntry] = []


class TmdbKeyword(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""


class TmdbKeywords(BaseModel):
    """Movie keywords arrive under `keywords`, TV keywords under `results`."""

    model_config = ConfigDict(extra="ignore")

    keywords: list[TmdbKeyword] = []
    results: list[TmdbKeyword] = []

    @property
    def all(self) -> list[TmdbKeyword]:
        return self.keywords or self.results


class TmdbCreator(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    name: str = ""


class TmdbDetail(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    id: int
    title: str | None = None
    name: str | None = None
    original_title: str | None = None
    original_name: str | None = None
    overview: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    release_date: str | None = None
    first_air_date: str | None = None
    vote_average: float = 0.0
    vote_count: int = 0
    popularity: float = 0.0
    original_language: str = ""
    tagline: str | None = None
    runtime: int | None = None
    episode_run_time: list[int] = []
    number_of_seasons: int | None = None
    genres: list[TmdbGenre] = []
    seasons: list[TmdbSeason] = []
    created_by: list[TmdbCreator] = []
    keywords: TmdbKeywords | None = None
    videos: TmdbVideos | None = None
    images: TmdbImages | None = None
    credits: TmdbCredits | None = None
    recommendations: TmdbMediaPage | None = None
    similar: TmdbMediaPage | None = None
    watch_providers: TmdbWatchProviders | None = Field(
        default=None, validation_alias="watch/providers"
    )
    release_dates: TmdbReleaseDates | None = None
    content_ratings: TmdbContentRatings | None = None


M = TypeVar("M", bound=BaseModel)


async def _sleep(seconds: float) -> None:  # indirection so tests can stub the backoff
    await asyncio.sleep(seconds)


def _retry_after(response: httpx.Response) -> float | None:
    raw = response.headers.get("retry-after")
    if raw is None:
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    return value if value > 0 else None


class TmdbClient:
    def __init__(self, http: httpx.AsyncClient, api_key: str | None, cache: Cache) -> None:
        self._http = http
        self._api_key = api_key
        self._cache = cache

    async def discover(
        self,
        media: MediaType,
        *,
        region: str,
        page: int = 1,
        sort_by: str = "popularity.desc",
        genres: list[int] | None = None,
        min_votes: int | None = None,
        release_gte: str | None = None,
        release_lte: str | None = None,
        providers: list[int] | None = None,
    ) -> TmdbMediaPage:
        params: dict[str, str | int] = {
            "language": LANGUAGE,
            "watch_region": region,
            "sort_by": sort_by,
            "page": page,
            "include_adult": "false",
        }
        if min_votes is not None:
            params["vote_count.gte"] = min_votes
        if genres:
            params["with_genres"] = ",".join(str(g) for g in genres)
        if providers:
            params["with_watch_providers"] = "|".join(str(provider) for provider in providers)
            params["with_watch_monetization_types"] = "flatrate"
        date_field = "primary_release_date" if media == "movie" else "first_air_date"
        if release_gte is not None:
            params[f"{date_field}.gte"] = release_gte
        if release_lte is not None:
            params[f"{date_field}.lte"] = release_lte
        return await self._cached(f"/discover/{media}", params, TTL_DISCOVER, TmdbMediaPage)

    async def trending(
        self,
        media: Literal["all", "movie", "tv"] = "all",
        window: Literal["day", "week"] = "day",
    ) -> TmdbMediaPage:
        return await self._cached(
            f"/trending/{media}/{window}", {"language": LANGUAGE}, TTL_TRENDING, TmdbMediaPage
        )

    async def multi_search(self, query: str) -> TmdbMediaPage:
        params: dict[str, str | int] = {
            "language": LANGUAGE,
            "query": query,
            "include_adult": "false",
            "page": 1,
        }
        return await self._cached("/search/multi", params, TTL_SEARCH, TmdbMediaPage)

    async def detail(self, media: MediaType, tmdb_id: int, region: str) -> TmdbDetail:
        params: dict[str, str | int] = {
            "language": LANGUAGE,
            "append_to_response": DETAIL_APPEND,
            "include_image_language": "en,null",
        }
        # region varies the cache key so certifications/providers stay correct.
        return await self._cached(
            f"/{media}/{tmdb_id}", {**params, "region": region}, TTL_DETAIL, TmdbDetail
        )

    async def genres(self, media: MediaType) -> list[TmdbGenre]:
        result = await self._cached(
            f"/genre/{media}/list", {"language": LANGUAGE}, TTL_GENRES, TmdbGenreList
        )
        return result.genres

    async def regions(self) -> list[TmdbRegion]:
        result = await self._cached(
            "/watch/providers/regions",
            {"language": LANGUAGE},
            TTL_REGIONS,
            TmdbRegionList,
        )
        return result.results

    async def providers(self, media: MediaType, region: str) -> list[TmdbProvider]:
        result = await self._cached(
            f"/watch/providers/{media}",
            {"language": LANGUAGE, "watch_region": region},
            TTL_PROVIDERS,
            TmdbProviderList,
        )
        return result.results

    async def probe(self) -> None:
        if self._api_key is None:
            raise CatalogNotConfigured
        data = await self._request("/configuration", {})
        try:
            TmdbConfiguration.model_validate(data)
        except ValidationError as error:
            raise UpstreamUnavailable("unexpected tmdb response shape") from error

    async def _cached(
        self, path: str, params: dict[str, str | int], opts: CacheOpts, model: type[M]
    ) -> M:
        if self._api_key is None:
            raise CatalogNotConfigured
        key = _cache_key(path, params)

        async def loader() -> M:
            data = await self._request(path, params)
            try:
                return model.model_validate(data)
            except ValidationError as error:
                raise UpstreamUnavailable("unexpected tmdb response shape") from error

        return await self._cache.cached(key, opts, loader)

    async def _request(self, path: str, params: dict[str, str | int]) -> object:
        url = f"{BASE}{path}"
        query: dict[str, str | int] = {**params, "api_key": self._api_key or ""}
        headers = {"Accept": "application/json"}
        attempt = 0
        while True:
            try:
                response = await self._http.get(
                    url, params=query, headers=headers, timeout=TIMEOUT_SECONDS
                )
            except httpx.HTTPError:
                if attempt < MAX_RETRIES:
                    await _sleep(BACKOFF_BASE_SECONDS * 2**attempt)
                    attempt += 1
                    continue
                # Fixed message + dropped cause: the httpx error and its request
                # carry the api_key-bearing URL, which must not reach logs or an
                # error tracker's captured __cause__ chain.
                raise UpstreamUnavailable("tmdb request failed") from None
            if response.status_code == 429 or response.status_code >= 500:
                if attempt < MAX_RETRIES:
                    await _sleep(_retry_after(response) or BACKOFF_BASE_SECONDS * 2**attempt)
                    attempt += 1
                    continue
                raise UpstreamUnavailable(f"tmdb returned {response.status_code}")
            if response.status_code >= 400:
                raise UpstreamRejected(response.status_code)
            try:
                return response.json()
            except ValueError as error:
                raise UpstreamUnavailable("tmdb returned non-JSON") from error


def _cache_key(path: str, params: dict[str, str | int]) -> str:
    items = sorted((k, str(v)) for k, v in params.items() if k != "api_key")
    return f"tmdb:{path}?" + "&".join(f"{k}={v}" for k, v in items)

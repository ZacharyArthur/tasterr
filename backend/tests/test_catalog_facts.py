"""Title facts for the taste engine: pure builder + cached-fetch reuse."""

from collections.abc import Callable
from pathlib import Path

import httpx
import pytest

from tasterr.cache import Cache
from tasterr.catalog.facts import to_facts
from tasterr.catalog.service import CatalogService
from tasterr.clients.tmdb import TmdbClient, TmdbDetail
from tasterr.main import create_app
from tasterr.settings import Settings

MOVIE_JSON = {
    "id": 42,
    "title": "Deep",
    "release_date": "2014-11-05",
    "runtime": 169,
    "original_language": "en",
    "vote_average": 8.4,
    "vote_count": 33000,
    "genres": [{"id": 878, "name": "Science Fiction"}, {"id": 18, "name": "Drama"}],
    "keywords": {"keywords": [{"id": 1, "name": "wormhole"}, {"id": 2, "name": "space travel"}]},
    "credits": {
        "cast": [
            {"id": 10, "name": "Second Billed", "order": 1},
            {"id": 9, "name": "Top Billed", "order": 0},
        ],
        "crew": [
            {"id": 20, "name": "The Director", "job": "Director"},
            {"id": 21, "name": "The Writer", "job": "Writer"},
        ],
    },
}

TV_JSON = {
    "id": 1399,
    "name": "A Show",
    "first_air_date": "2011-04-17",
    "episode_run_time": [55],
    "original_language": "en",
    "vote_average": 8.5,
    "vote_count": 21000,
    "created_by": [{"id": 9813, "name": "Show Runner"}],
    "keywords": {"results": [{"id": 6091, "name": "war"}]},
}


def test_movie_facts_carry_keywords_cast_and_director() -> None:
    facts = to_facts(TmdbDetail.model_validate(MOVIE_JSON), "movie", "US")

    assert facts.tmdb_id == 42
    assert facts.title == "Deep"
    assert facts.genres == ["Science Fiction", "Drama"]
    assert facts.keywords == ["wormhole", "space travel"]
    assert facts.cast == ["Top Billed", "Second Billed"]  # billing order, not wire order
    assert facts.creators == ["The Director"]  # director only, not the writer
    assert facts.original_language == "en"
    assert facts.year == 2014
    assert facts.runtime == 169
    assert facts.vote_average == 8.4
    assert facts.vote_count == 33000


def test_tv_facts_use_created_by_and_episode_runtime() -> None:
    facts = to_facts(TmdbDetail.model_validate(TV_JSON), "tv", "US")

    assert facts.creators == ["Show Runner"]
    assert facts.keywords == ["war"]
    assert facts.year == 2011
    assert facts.runtime == 55


def test_bare_detail_yields_empty_facts() -> None:
    facts = to_facts(TmdbDetail(id=1), "movie", "US")

    assert facts.title == "Untitled"
    assert facts.genres == []
    assert facts.keywords == []
    assert facts.cast == []
    assert facts.creators == []


@pytest.mark.parametrize(
    ("language", "expected_reads"),
    [("en-US", ["en-US"]), ("en-GB", ["en-GB", "en-US"])],
)
async def test_detail_and_facts_share_cache_only_for_engine_language(
    language: str, expected_reads: list[str]
) -> None:
    reads: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        reads.append(request.url.params["language"])
        return httpx.Response(200, json=MOVIE_JSON)

    service = _service(handler, language)
    await service.detail("movie", 42)
    facts = await service.title_facts("movie", 42)

    assert reads == expected_reads
    assert facts.keywords == ["wormhole", "space travel"]


async def test_spanish_display_keeps_english_facts_and_engine_genres() -> None:
    seen: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        language = request.url.params["language"]
        seen.append((request.url.path, language))
        genres = [
            {"id": 878, "name": "Ciencia ficción" if language == "es-ES" else "Science Fiction"}
        ]
        if "/genre/" in request.url.path:
            return httpx.Response(200, json={"genres": genres})
        return httpx.Response(
            200,
            json={
                **MOVIE_JSON,
                "title": "Profundo" if language == "es-ES" else "Deep",
                "genres": genres,
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        service = CatalogService(TmdbClient(http, "key", Cache()), language="es-ES")
        assert (await service.detail("movie", 42)).title == "Profundo"
        assert (await service.title_facts("movie", 42)).genres == ["Science Fiction"]
        assert (await service.title_facts("movie", 42)).title == "Deep"
        assert await service.genre_map("movie") == {"Science Fiction": 878}
        assert (await service.genres("movie"))[0].name == "Ciencia ficción"
    assert seen == [
        ("/3/movie/42", "es-ES"),
        ("/3/movie/42", "en-US"),
        ("/3/genre/movie/list", "en-US"),
        ("/3/genre/movie/list", "es-ES"),
    ]


def test_facts_never_appear_in_the_api_schema(tmp_path: Path) -> None:
    settings = Settings.model_validate(
        {"database_path": tmp_path / "tasterr.db", "static_dir": tmp_path / "static"}
    )
    schema = create_app(settings).openapi()

    assert "TitleFacts" not in schema.get("components", {}).get("schemas", {})


def _service(handler: Callable[[httpx.Request], httpx.Response], language: str) -> CatalogService:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return CatalogService(TmdbClient(http, "key", Cache()), language=language)

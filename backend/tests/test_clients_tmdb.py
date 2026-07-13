"""TMDB client contract tests on httpx.MockTransport (task 1.3)."""

from collections.abc import Callable

import httpx
import pytest

import tasterr.clients.tmdb as tmdb_mod
from tasterr.cache import Cache
from tasterr.clients.errors import UpstreamRejected, UpstreamUnavailable
from tasterr.clients.tmdb import CatalogNotConfigured, TmdbClient

API_KEY = "tmdb-key-sentinel"

DISCOVER_JSON = {
    "page": 1,
    "total_pages": 5,
    "results": [
        {
            "id": 1,
            "title": "A Movie",
            "poster_path": "/p.jpg",
            "vote_average": 7.5,
            "release_date": "2020-05-01",
        }
    ],
}

DETAIL_JSON = {
    "id": 42,
    "title": "Deep",
    "genres": [{"id": 18, "name": "Drama"}],
    "runtime": 120,
    "videos": {"results": [{"key": "abc", "site": "YouTube", "type": "Trailer", "official": True}]},
    "credits": {"cast": [{"id": 9, "name": "Actor", "character": "Hero", "order": 0}]},
    "watch/providers": {
        "results": {
            "US": {
                "flatrate": [
                    {
                        "provider_id": 8,
                        "provider_name": "Netflix",
                        "logo_path": "/n.png",
                        "display_priority": 1,
                    }
                ]
            }
        }
    },
}


def _client(
    handler: Callable[[httpx.Request], httpx.Response], api_key: str | None = API_KEY
) -> TmdbClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return TmdbClient(http, api_key, Cache())


async def _noop_sleep(_: float) -> None:
    return None


async def test_discover_parses_results_and_sends_key() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/discover/movie"
        assert request.url.params["api_key"] == API_KEY
        assert request.url.params["watch_region"] == "US"
        return httpx.Response(200, json=DISCOVER_JSON)

    page = await _client(handler).discover("movie", region="US")

    assert [r.id for r in page.results] == [1]
    assert page.results[0].title == "A Movie"
    assert page.total_pages == 5


async def test_discover_serializes_selected_services_as_flate_rate_or() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["with_watch_providers"] == "8|337"
        assert request.url.params["with_watch_monetization_types"] == "flatrate"
        return httpx.Response(200, json=DISCOVER_JSON)

    await _client(handler).discover("movie", region="GB", providers=[8, 337])


async def test_discover_omits_provider_parameters_for_empty_selection() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "with_watch_providers" not in request.url.params
        assert "with_watch_monetization_types" not in request.url.params
        return httpx.Response(200, json=DISCOVER_JSON)

    await _client(handler).discover("movie", region="US", providers=[])


async def test_detail_parses_appended_blocks() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/movie/42"
        append = request.url.params["append_to_response"]
        # certification lives in these appends — omitting them makes it null.
        assert "release_dates" in append
        assert "content_ratings" in append
        return httpx.Response(200, json=DETAIL_JSON)

    detail = await _client(handler).detail("movie", 42, "US")

    assert detail.id == 42
    assert detail.runtime == 120
    assert detail.videos is not None
    assert detail.videos.results[0].key == "abc"
    assert detail.watch_providers is not None
    assert "US" in detail.watch_providers.results


async def test_detail_requests_and_parses_movie_keywords() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "keywords" in request.url.params["append_to_response"]
        payload = {
            **DETAIL_JSON,
            "keywords": {"keywords": [{"id": 4565, "name": "dystopia"}]},
        }
        return httpx.Response(200, json=payload)

    detail = await _client(handler).detail("movie", 42, "US")

    assert detail.keywords is not None
    assert [k.name for k in detail.keywords.all] == ["dystopia"]


async def test_detail_parses_tv_keywords_and_creator() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        payload = {
            "id": 1399,
            "name": "A Show",
            "created_by": [{"id": 9813, "name": "Show Runner"}],
            "keywords": {"results": [{"id": 6091, "name": "war"}]},
        }
        return httpx.Response(200, json=payload)

    detail = await _client(handler).detail("tv", 1399, "US")

    assert [c.name for c in detail.created_by] == ["Show Runner"]
    assert detail.keywords is not None
    assert [k.name for k in detail.keywords.all] == ["war"]


async def test_detail_tolerates_absent_keywords() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DETAIL_JSON)

    detail = await _client(handler).detail("movie", 42, "US")

    assert detail.keywords is None
    assert detail.created_by == []


async def test_genres_returns_list() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/genre/movie/list"
        return httpx.Response(200, json={"genres": [{"id": 28, "name": "Action"}]})

    genres = await _client(handler).genres("movie")

    assert [g.name for g in genres] == ["Action"]


async def test_regions_and_providers_are_typed_and_cached_by_region() -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/regions"):
            return httpx.Response(
                200,
                json={
                    "results": [
                        {"iso_3166_1": "GB", "english_name": "United Kingdom", "ignored": 1}
                    ]
                },
            )
        return httpx.Response(
            200,
            json={
                "results": [
                    {
                        "provider_id": 8,
                        "provider_name": "Netflix",
                        "logo_path": "/n.png",
                        "display_priorities": {"GB": 2, "US": 5},
                    }
                ]
            },
        )

    client = _client(handler)
    assert (await client.regions())[0].english_name == "United Kingdom"
    assert (await client.regions())[0].iso_3166_1 == "GB"
    gb = await client.providers("movie", "GB")
    us = await client.providers("movie", "US")
    assert gb[0].priority_for("GB") == 2
    assert us[0].priority_for("US") == 5
    assert len(calls) == 3


async def test_probe_requires_typed_configuration() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/3/configuration"
        return httpx.Response(200, json={"images": {"secure_base_url": "https://image/"}})

    await _client(handler).probe()


async def test_probe_rejects_malformed_configuration() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"not_images": {}})

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).probe()


async def test_second_identical_call_is_cached() -> None:
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=DISCOVER_JSON)

    client = _client(handler)
    await client.discover("movie", region="US")
    await client.discover("movie", region="US")

    assert calls == 1


async def test_retries_on_429_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tmdb_mod, "_sleep", _noop_sleep)
    calls = 0

    def handler(_: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            return httpx.Response(429, headers={"retry-after": "0"}, json={})
        return httpx.Response(200, json=DISCOVER_JSON)

    page = await _client(handler).discover("movie", region="US")

    assert calls == 2
    assert page.results[0].id == 1


async def test_persistent_5xx_is_unavailable_without_leaking_body(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(tmdb_mod, "_sleep", _noop_sleep)

    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="upstream boom secret detail")

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _client(handler).discover("movie", region="US")

    assert "boom" not in str(excinfo.value)  # upstream body never surfaces


async def test_unknown_id_is_rejected() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"status_message": "The resource you requested..."})

    with pytest.raises(UpstreamRejected) as excinfo:
        await _client(handler).detail("movie", 999, "US")

    assert excinfo.value.status_code == 404


async def test_missing_key_raises_not_configured() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=DISCOVER_JSON)

    with pytest.raises(CatalogNotConfigured):
        await _client(handler, api_key=None).discover("movie", region="US")


async def test_malformed_json_is_unavailable() -> None:
    def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="not json", headers={"content-type": "text/plain"})

    with pytest.raises(UpstreamUnavailable):
        await _client(handler).discover("movie", region="US")


async def test_transport_error_message_carries_no_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(tmdb_mod, "_sleep", _noop_sleep)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    with pytest.raises(UpstreamUnavailable) as excinfo:
        await _client(handler).discover("movie", region="US")

    assert API_KEY not in str(excinfo.value)  # the api_key rides in the request URL
    assert excinfo.value.__cause__ is None  # chain dropped so no tracker captures the URL


async def test_no_browser_headers_are_forwarded() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert "cookie" not in request.headers
        assert "authorization" not in request.headers
        return httpx.Response(200, json=DISCOVER_JSON)

    await _client(handler).discover("movie", region="US")

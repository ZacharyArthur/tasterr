"""Continue Watching retains its per-user presentation cache across language changes."""

from types import SimpleNamespace
from typing import cast

import httpx
import pytest
from pydantic import SecretStr

import tasterr.cache as cache_module
from tasterr.cache import Cache
from tasterr.catalog.plex import PlexCatalogService
from tasterr.catalog.service import CatalogService
from tasterr.clients.plex import (
    PlexCloudAccount,
    PlexGuid,
    PlexMediaClient,
    PlexPmsItem,
    PlexServer,
    PlexServerDiscovery,
)
from tasterr.clients.tmdb import TmdbClient


async def test_continue_watching_changes_language_only_after_five_minute_expiry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1000.0
    monkeypatch.setattr(cache_module, "time", SimpleNamespace(monotonic=lambda: now))
    server = PlexServer(
        base_url="https://test.plex.direct:32400",
        machine_identifier="test",
        access_token=SecretStr("test-token"),
    )

    class Plex:
        async def account(self, token: str) -> PlexCloudAccount:
            return PlexCloudAccount(id=1, username="viewer")

        async def discover_servers(self, token: str) -> PlexServerDiscovery:
            return PlexServerDiscovery((server,), True)

        async def continue_watching(self, server: PlexServer) -> list[PlexPmsItem]:
            return [
                PlexPmsItem(
                    type="movie",
                    ratingKey=42,
                    Guid=[PlexGuid(id="tmdb://42")],
                    viewOffset=50,
                    duration=100,
                    lastViewedAt=100,
                )
            ]

    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        language = request.url.params["language"]
        seen.append(language)
        return httpx.Response(
            200,
            json={
                "id": 42,
                "title": "Deep" if language == "en-US" else "Profundo",
                "overview": language,
            },
        )

    cache = Cache()
    plex = cast("PlexMediaClient", Plex())
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        tmdb = TmdbClient(http, "test-key", cache)
        english = PlexCatalogService(plex, CatalogService(tmdb, language="en-US"), cache)
        spanish = PlexCatalogService(plex, CatalogService(tmdb, language="es-ES"), cache)
        assert (await english.continue_watching(1, "test-token"))[0].title == "Deep"
        now += 299
        cached = await spanish.continue_watching(1, "test-token")
        assert (cached[0].title, cached[0].overview) == ("Deep", "en-US")
        assert seen == ["en-US"]
        now += 1
        refreshed = await spanish.continue_watching(1, "test-token")
        assert (refreshed[0].title, refreshed[0].overview) == ("Profundo", "es-ES")
        assert seen == ["en-US", "es-ES"]

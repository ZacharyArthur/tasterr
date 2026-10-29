# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from pathlib import Path
from typing import cast

import httpx
import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_account_api import db_call, login
from tests.test_auth_api import PLEX_TOKEN, SECRET, _harness, _poll_pin, _start_pin_login
from tests.test_browse_api import FakeCatalog
from tests.test_catalog_jellyfin import item
from tests.test_clients_jellyfin import KEY, USER_ID
from tests.test_jellyfin_auth import BODY, JellyfinUpstream

from tasterr.api.auth import AuthContext, get_auth_context
from tasterr.api.availability import get_availability
from tasterr.api.catalog import get_catalog
from tasterr.auth.crypto import decrypt_token, encrypt_token
from tasterr.auth.login import get_link
from tasterr.cache import Cache
from tasterr.catalog.availability import AvailabilityService
from tasterr.catalog.models import HomeFeed
from tasterr.catalog.resume import ResumeCandidate
from tasterr.catalog.service import CatalogService
from tasterr.clients.jellyfin import JellyfinClient
from tasterr.clients.plex import PlexAuthClient
from tasterr.clients.seerr import SeerrAuthClient, SeerrClient
from tasterr.db.models import LinkedAccount, Provider
from tasterr.settings import Settings, get_settings


def _continue_ids(response: httpx.Response) -> set[int]:
    assert response.status_code == 200
    feed = HomeFeed.model_validate(response.json())
    return {item.id for rail in feed.rails if rail.id == "continue-watching" for item in rail.items}


@pytest.mark.parametrize("provider", ["plex", "jellyfin"])
@pytest.mark.parametrize("negative", [False, True])
@pytest.mark.parametrize("mode", ["bridge", "refresh"])
def test_media_sign_in_refreshes_shared_resume_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    provider: Provider,
    negative: bool,
    mode: str,
) -> None:
    harness = _harness(tmp_path)
    settings = cast(Settings, harness.app.dependency_overrides[get_settings]())
    settings.jellyfin_internal_url = "http://jellyfin"
    settings.jellyfin_api_key = SecretStr(KEY)
    upstream = JellyfinUpstream()
    upstream.seerr_status = 200
    ready = False
    old_ids = set() if negative else set(range(30, 34))
    new_ids = set(range(40, 44))
    plex_tokens: list[str] = []

    def visible_ids(source: str) -> set[int]:
        if source == provider:
            return new_ids if ready else old_ids
        return old_ids if mode == "bridge" else set()

    def respond(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/UserItems/Resume":
            assert request.url.params["userId"] == USER_ID
            rows = [item(i) for i in sorted(visible_ids("jellyfin"))]
            return httpx.Response(200, json={"Items": rows, "TotalRecordCount": len(rows)})
        if path == "/Shows/NextUp":
            assert request.url.params["userId"] == USER_ID
            return httpx.Response(200, json={"Items": [], "TotalRecordCount": 0})
        return upstream.respond(request)

    class Plex:
        def __init__(self, *_args: object) -> None:
            pass

        async def resume_candidates(self, token: str) -> list[ResumeCandidate]:
            plex_tokens.append(token)
            return [
                ResumeCandidate("movie", i, 100, (0, 0), 40) for i in sorted(visible_ids("plex"))
            ]

    async def no_history(*_args: object) -> None:
        pass

    monkeypatch.setattr("tasterr.api.home.PlexCatalogService", Plex)
    monkeypatch.setattr("tasterr.api.home.schedule_history", no_history)
    monkeypatch.setattr("tasterr.api.auth.schedule_history", no_history)
    harness.app.dependency_overrides[get_catalog] = lambda: cast(CatalogService, FakeCatalog())
    harness.app.dependency_overrides[get_availability] = lambda: AvailabilityService(None, Cache())
    http = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    ctx = AuthContext(
        secret_key=SECRET,
        plex=cast(PlexAuthClient, harness.plex),
        seerr=SeerrAuthClient(http, "http://seerr"),
        pins=harness.pins,
        seerr_read=SeerrClient(http, "http://seerr", "fixture-key"),
        jellyfin=JellyfinClient(http, "http://jellyfin", KEY, "device"),
    )
    harness.app.dependency_overrides[get_auth_context] = lambda: ctx

    async def seed(db: AsyncSession) -> None:
        source: Provider = (
            ("jellyfin" if provider == "plex" else "plex") if mode == "bridge" else provider
        )
        db.add(
            LinkedAccount(
                user_id=1,
                provider=source,
                external_id="8" if source == "plex" else USER_ID,
                display_name="Viewer",
                credential_enc=encrypt_token(SECRET, "old-token") if source == "plex" else None,
            )
        )

    try:
        with TestClient(harness.app) as client:
            harness.app.state.http = http
            login(client)
            db_call(harness.db_path, seed)
            assert _continue_ids(client.get("/api/v1/home")) == old_ids
            if provider == "plex":
                harness.plex.token = PLEX_TOKEN
                response = _poll_pin(client, _start_pin_login(client))
                assert response.status_code == 200 and response.json()["status"] == "ok"
                assert response.json()["user"]["id"] == 1
            else:
                response = client.post("/api/v1/auth/jellyfin", json=BODY)
                assert response.status_code == 200 and response.json()["id"] == 1

            async def verify_link(db: AsyncSession) -> None:
                link = await get_link(db, 1, provider)
                assert link is not None
                if provider == "plex":
                    assert decrypt_token(SECRET, link.credential_enc or "") == PLEX_TOKEN

            db_call(harness.db_path, verify_link)
            ready = True
            expected = new_ids | old_ids if mode == "bridge" else new_ids
            assert _continue_ids(client.get("/api/v1/home")) == expected
            if provider == "plex":
                assert plex_tokens[-1] == PLEX_TOKEN
    finally:
        asyncio.run(http.aclose())

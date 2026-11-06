"""Local Trakt transport and authenticated application fixtures."""

import asyncio
import json
import time
from collections.abc import AsyncGenerator, Awaitable, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast

import httpx
from fastapi import FastAPI
from pydantic import SecretStr
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from tests.test_account_api import LOCAL
from tests.test_auth_api import SECRET, _harness  # pyright: ignore[reportPrivateUsage]

from tasterr.auth.crypto import encrypt_token
from tasterr.auth.login import get_link
from tasterr.auth.pins import PinStore
from tasterr.auth.trakt import DeviceAttempt, TraktCredential
from tasterr.clients.trakt import TraktClient
from tasterr.db.models import LinkedAccount, utcnow
from tasterr.settings import Settings, get_settings


def entry(index: int, *, show: bool = False, days: int = 1) -> dict[str, object]:
    return {
        "watched_at": (datetime.now(UTC) - timedelta(days=days)).isoformat(),
        "show" if show else "movie": {"ids": {"tmdb": index}},
        "episode": {"ids": {"tmdb": 999999}},
        "id": 12345,
    }


class FakeTrakt:
    def __init__(self) -> None:
        self.requests: list[httpx.Request] = []
        self.poll_status = 200
        self.settings_status = 200
        self.refresh_status = 200
        self.revoke_status = 200
        self.expires_in = 600
        self.uuid = "stable-fixture-uuid"
        self.username = "Trakt fixture"
        self.pages: dict[tuple[str, int], list[dict[str, object]]] = {
            ("movies", 1): [entry(550)],
            ("episodes", 1): [entry(1399, show=True)],
        }
        self.page_count: int | None = 1
        self.page_limit: int | None = 250
        self.fail_page: tuple[str, int] | None = None
        self.activities: dict[str, object] = {}
        self.refresh_started = asyncio.Event()
        self.refresh_release = asyncio.Event()
        self.refresh_release.set()
        self.history_started = asyncio.Event()
        self.history_release = asyncio.Event()
        self.history_release.set()
        self.history_cancelled = asyncio.Event()
        self.delay = 0.0
        self.on_read: Callable[[httpx.Request], Awaitable[None]] | None = None
        self.on_revoke: Callable[[str], Awaitable[None]] | None = None

    async def respond(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        path = request.url.path
        if path == "/oauth/device/code":
            return httpx.Response(
                200,
                json={
                    "device_code": "device-fixture",
                    "user_code": "ABC123",
                    "interval": 6,
                    "expires_in": self.expires_in,
                    "verification_url": "https://untrusted.invalid",
                },
            )
        if path in ("/oauth/device/token", "/oauth/token"):
            refresh = path == "/oauth/token"
            if refresh:
                self.refresh_started.set()
                await self.refresh_release.wait()
            status = self.refresh_status if refresh else self.poll_status
            return httpx.Response(
                status,
                json={
                    "access_token": "rotated-access" if refresh else "device-access",
                    "refresh_token": "rotated-refresh" if refresh else "device-refresh",
                    "created_at": int(time.time()),
                    "expires_in": 3600,
                },
            )
        if path == "/users/settings":
            return httpx.Response(
                self.settings_status,
                json={
                    "user": {
                        "username": self.username,
                        "ids": {"uuid": self.uuid, "slug": "mutable-fixture-slug"},
                    }
                },
            )
        if path == "/sync/last_activities":
            return httpx.Response(200, json=self.activities)
        if path.startswith("/sync/history/"):
            self.history_started.set()
            try:
                await self.history_release.wait()
                await asyncio.sleep(self.delay)
            except asyncio.CancelledError:
                self.history_cancelled.set()
                raise
            if self.on_read:
                await self.on_read(request)
            key = (path.rsplit("/", 1)[-1], int(request.url.params["page"]))
            headers: dict[str, str] = {}
            if self.page_count is not None:
                headers["X-Pagination-Page-Count"] = str(self.page_count)
            if self.page_limit is not None:
                headers["X-Pagination-Limit"] = str(self.page_limit)
            return httpx.Response(
                401 if key == self.fail_page else 200, json=self.pages.get(key, []), headers=headers
            )
        if path == "/oauth/revoke":
            if self.on_revoke:
                await self.on_revoke(str(json.loads(request.content)["token"]))
            return httpx.Response(self.revoke_status)
        return httpx.Response(503)


@dataclass
class TraktFixture:
    app: FastAPI
    client: httpx.AsyncClient
    upstream: FakeTrakt
    settings: Settings
    maker: async_sessionmaker[AsyncSession]
    trakt_client: TraktClient

    async def seed(self, *, expires: int = 3600, synced: datetime | None = None) -> None:
        async with self.maker() as db:
            credential = TraktCredential(
                access_token="original-access",
                refresh_token="original-refresh",
                expires_at=time.time() + expires,
            )
            db.add(
                LinkedAccount(
                    user_id=1,
                    provider="trakt",
                    external_id=self.upstream.uuid,
                    display_name=self.upstream.username,
                    credential_enc=encrypt_token(SECRET, credential.model_dump_json()),
                    sync_synced_at=synced,
                )
            )
            await db.commit()

    async def create_handle(self) -> str:
        response = await self.client.post("/api/v1/account/links/trakt/device")
        assert response.status_code == 200
        assert set(response.json()) == {"handle", "user_code", "interval", "expires_in"}
        assert "device-fixture" not in response.text
        return str(response.json()["handle"])

    async def poll(self, handle: str) -> httpx.Response:
        pins = cast("PinStore[DeviceAttempt]", self.app.state.trakt_pin_store)
        for pending in pins._pending.values():  # pyright: ignore[reportPrivateUsage]
            pending.payload.last_poll = 0
        return await self.client.post(
            "/api/v1/account/links/trakt/device/poll", json={"handle": handle}
        )

    async def unthrottle(self) -> None:
        async with self.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None
            link.sync_attempted_at = utcnow() - timedelta(hours=7)
            await db.commit()


@asynccontextmanager
async def trakt_harness(tmp_path: Path) -> AsyncGenerator[TraktFixture]:
    harness = _harness(tmp_path)
    settings = cast("Settings", harness.app.dependency_overrides[get_settings]())
    settings.trakt_client_id = SecretStr("client-fixture")
    fake = FakeTrakt()
    async with (
        httpx.AsyncClient(transport=httpx.MockTransport(fake.respond)) as upstream,
        harness.app.router.lifespan_context(harness.app),
    ):
        harness.app.state.http = upstream
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client:
            assert (await client.post("/api/v1/auth/local", json=LOCAL)).status_code == 200
            maker = cast("async_sessionmaker[AsyncSession]", harness.app.state.sessionmaker)
            yield TraktFixture(
                harness.app, client, fake, settings, maker, TraktClient(upstream, "client-fixture")
            )

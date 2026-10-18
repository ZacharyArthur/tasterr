# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
import asyncio
from datetime import timedelta
from pathlib import Path

import httpx
import pytest
from sqlalchemy import update
from starlette.types import Message, Receive, Scope, Send
from tests.test_account_api import LOCAL
from tests.test_auth_api import _harness

from tasterr.db.models import UserSession, utcnow


@pytest.mark.parametrize("sliding", [False, True])
async def test_delayed_deletion_cannot_erase_a_new_login_cookie(
    tmp_path: Path, sliding: bool
) -> None:
    harness = _harness(tmp_path)
    deleting, release = asyncio.Event(), asyncio.Event()

    async def delayed_app(scope: Scope, receive: Receive, send: Send) -> None:
        async def delayed_send(message: Message) -> None:
            if (
                scope.get("path") == "/api/v1/account/delete"
                and message["type"] == "http.response.start"
            ):
                deleting.set()
                await release.wait()
            await send(message)

        await harness.app(scope, receive, delayed_send)

    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=delayed_app), base_url="http://testserver"
        ) as browser,
        asyncio.timeout(10),
    ):
        first = await browser.post("/api/v1/auth/local", json=LOCAL)
        assert first.status_code == 200
        if sliding:
            async with harness.app.state.sessionmaker() as db:
                await db.execute(
                    update(UserSession).values(last_seen_at=utcnow() - timedelta(hours=2))
                )
                await db.commit()
        deletion = asyncio.create_task(
            browser.post("/api/v1/account/delete", json={"confirm": "Viewer"})
        )
        try:
            await deleting.wait()
            newer = await browser.post("/api/v1/auth/local", json=LOCAL)
            assert newer.status_code == 200 and newer.json()["id"] != first.json()["id"]
            cookie = browser.cookies.get("tasterr_session")
            assert cookie is not None
            assert (await browser.get("/api/v1/auth/me")).status_code == 200
            release.set()
            deleted = await deletion
            assert deleted.status_code == 204
            assert "set-cookie" not in deleted.headers
            assert browser.cookies.get("tasterr_session") == cookie
            assert (await browser.get("/api/v1/auth/me")).status_code == 200
        finally:
            release.set()
            await asyncio.gather(deletion, return_exceptions=True)

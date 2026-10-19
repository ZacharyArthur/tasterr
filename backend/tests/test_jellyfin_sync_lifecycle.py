# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import asyncio
from pathlib import Path

import httpx
import pytest
from tests.test_jellyfin_auth import BODY, jellyfin_harness


async def test_login_trigger_onboarding_pending_and_reset_restarts_background_sync(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    harness = jellyfin_harness(tmp_path, monkeypatch)
    calls = 0
    cancelled = asyncio.Event()

    async def import_history(*_args: object) -> None:
        nonlocal calls
        calls += 1
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr("tasterr.api.taste.import_jellyfin_history", import_history)
    async with (
        harness.app.router.lifespan_context(harness.app),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=harness.app), base_url="http://testserver"
        ) as client,
    ):
        assert (await client.post("/api/v1/auth/jellyfin", json=BODY)).status_code == 200
        assert (await client.get("/api/v1/taste-onboarding")).json() == {"state": "pending"}
        first = harness.app.state.jellyfin_history_tasks[1]
        await asyncio.sleep(0)
        assert calls == 1
        assert (await client.post("/api/v1/recommendations/reset")).status_code == 204
        assert cancelled.is_set() and first.cancelled()
        assert (await client.get("/api/v1/taste-onboarding")).json() == {"state": "pending"}
        assert calls == 2

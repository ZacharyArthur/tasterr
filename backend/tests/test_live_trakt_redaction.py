import subprocess
import sys
from pathlib import Path


def test_live_trakt_failures_hide_credentials_identities_and_payloads(tmp_path: Path) -> None:
    probe = tmp_path / "test_redaction_probe.py"
    probe.write_text(
        "import httpx\n"
        "import pytest\n"
        "import json\n"
        "from contextlib import asynccontextmanager\n"
        "from datetime import UTC, datetime, timedelta\n"
        "from tests.live import test_trakt_live as contracts\n"
        "from tests.live.test_trakt_live import (\n"
        "    _Grant, _Live, _redacted, _require,\n"
        "    test_history_plain_date_narrows_results as date_contract,\n"
        "    test_history_without_item_id_limits_and_pages as page_contract,\n"
        ")\n"
        "from tasterr.clients.trakt import TokenResponse, TraktClient\n"
        'PRIVATE = "synthetic-private-"\n'
        "def history_state(http):\n"
        '    live = _Live(TraktClient(http, PRIVATE + "client-id"))\n'
        "    grant = _Grant(TokenResponse(\n"
        '        access_token=PRIVATE + "access-token",\n'
        '        refresh_token=PRIVATE + "refresh-token",\n'
        "        created_at=0, expires_in=600))\n"
        "    return live, grant\n"
        "def test_identity_failure():\n"
        '    username = PRIVATE + "username-slug-title-uuid"\n'
        '    _require(username == "other", "Trakt stable user uuid missing")\n'
        "async def test_shape_failure():\n"
        '    payload = {"user_code": PRIVATE + "user-code",\n'
        '               "device_code": PRIVATE + "device-code"}\n'
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(\n"
        "        lambda _: httpx.Response(200, json=payload)\n"
        "    )) as http:\n"
        '        async with _redacted("Trakt device-code contract failed"):\n'
        '            await TraktClient(http, PRIVATE + "client-id",\n'
        '                              PRIVATE + "client-secret").device_code()\n'
        "async def test_transport_failure():\n"
        "    def fail(request):\n"
        '        raise RuntimeError(PRIVATE + "token-body-url")\n'
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(fail)) as http:\n"
        '        async with _redacted("Trakt transport contract failed"):\n'
        '            await TraktClient(http, PRIVATE + "client-id").user_settings(\n'
        '                PRIVATE + "access-token")\n'
        "async def test_pagination_failure():\n"
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(\n"
        '        lambda _: httpx.Response(200, json=[], headers={"X-Pagination-Limit": "1"})\n'
        "    )) as http:\n"
        '        live = _Live(TraktClient(http, PRIVATE + "client-id"))\n'
        '        async with _redacted("Trakt pagination contract failed"):\n'
        '            await live.history(PRIVATE + "access-token", "movies", limit=1)\n'
        "async def test_ignored_date_failure():\n"
        "    payload = [\n"
        '        {"watched_at": "2026-01-02T12:00:00Z", "title": PRIVATE + "title"},\n'
        '        {"watched_at": "2026-01-01T12:00:00Z", "slug": PRIVATE + "slug"},\n'
        "    ]\n"
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(\n"
        "        lambda _: httpx.Response(200, json=payload)\n"
        "    )) as http:\n"
        "        live, grant = history_state(http)\n"
        '        await date_contract(live, grant, "movies")\n'
        '@pytest.mark.parametrize("media_type", ["movies", "episodes"])\n'
        '@pytest.mark.parametrize("contract", [page_contract, date_contract])\n'
        "async def test_reversed_history(contract, media_type):\n"
        "    plays = [\n"
        '        {"watched_at": "2026-01-01T12:00:00Z", "title": PRIVATE + "title"},\n'
        '        {"watched_at": "2026-01-02T12:00:00Z", "slug": PRIVATE + "slug"},\n'
        "    ]\n"
        "    def respond(request):\n"
        "        rows = plays\n"
        '        start = request.url.params.get("start_at")\n'
        "        if start:\n"
        '            rows = [row for row in rows if row["watched_at"][:10] >= start]\n'
        '        limit = int(request.url.params["limit"])\n'
        '        page = int(request.url.params["page"])\n'
        "        return httpx.Response(200, json=rows[(page - 1) * limit:page * limit])\n"
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:\n"
        "        live, grant = history_state(http)\n"
        "        await contract(live, grant, media_type)\n"
        '@pytest.mark.parametrize("media_type", ["movies", "episodes"])\n'
        '@pytest.mark.parametrize("new_day_plays", [3, 250, 260])\n'
        '@pytest.mark.parametrize("lossy", [False, True])\n'
        "async def test_date_filter_completeness(media_type, new_day_plays, lossy):\n"
        "    latest = datetime(2026, 1, 2, 20, tzinfo=UTC)\n"
        '    plays = [{"watched_at": (latest - timedelta(seconds=i)).isoformat()}\n'
        "             for i in range(new_day_plays - 1)]\n"
        "    plays.extend([\n"
        '        {"watched_at": "2026-01-02T01:00:00Z", "title": PRIVATE + "title"},\n'
        '        {"watched_at": "2026-01-01T20:00:00Z", "slug": PRIVATE + "slug"},\n'
        "    ])\n"
        "    def respond(request):\n"
        "        rows = plays\n"
        '        start = request.url.params.get("start_at")\n'
        "        if start:\n"
        '            bound = start + ("T05:00:00" if lossy else "T00:00:00")\n'
        '            rows = [row for row in rows if row["watched_at"] >= bound]\n'
        '        limit = int(request.url.params["limit"])\n'
        '        page = int(request.url.params["page"])\n'
        "        return httpx.Response(200, json=rows[(page - 1) * limit:page * limit])\n"
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:\n"
        "        live, grant = history_state(http)\n"
        "        await date_contract(live, grant, media_type)\n"
        "@asynccontextmanager\n"
        "async def approved_grant(monkeypatch, fail_first_revoke=False):\n"
        '    monkeypatch.setenv("TASTERR_LIVE_TRAKT_INTERACTIVE", "true")\n'
        "    revoked, attempts = set(), []\n"
        "    def respond(request):\n"
        "        path = request.url.path\n"
        '        if path == "/oauth/device/code":\n'
        '            return httpx.Response(200, json={"device_code": PRIVATE + "device",\n'
        '                "user_code": "FAKECODE", "interval": 1, "expires_in": 600})\n'
        '        if path in ("/oauth/device/token", "/oauth/token"):\n'
        '            prefix = "new" if path == "/oauth/token" else "old"\n'
        '            return httpx.Response(200, json={"access_token": PRIVATE + prefix,\n'
        '                "refresh_token": PRIVATE + prefix + "-refresh",\n'
        '                "created_at": 0, "expires_in": 600})\n'
        '        if path == "/oauth/revoke":\n'
        '            token = json.loads(request.content)["token"]\n'
        "            attempts.append(token)\n"
        "            if fail_first_revoke and len(attempts) == 1:\n"
        '                return httpx.Response(503, text=PRIVATE + "upstream-body")\n'
        "            revoked.add(token)\n"
        "            return httpx.Response(200)\n"
        '        token = request.headers["Authorization"].removeprefix("Bearer ")\n'
        "        if token in revoked:\n"
        "            return httpx.Response(401)\n"
        '        return httpx.Response(200, json={"user": {"username": PRIVATE + "name",\n'
        '            "ids": {"uuid": PRIVATE + "uuid"}}})\n'
        "    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as http:\n"
        '        live = _Live(TraktClient(http, PRIVATE + "client-id"))\n'
        "        fixture = contracts.grant.__wrapped__(live)\n"
        "        grant = await anext(fixture)\n"
        "        try:\n"
        "            yield live, grant, revoked, attempts\n"
        "        finally:\n"
        "            try:\n"
        "                await anext(fixture)\n"
        "            except StopAsyncIteration:\n"
        "                pass\n"
        "async def test_rotation_cleanup_revokes_both(monkeypatch):\n"
        "    async with approved_grant(monkeypatch) as (live, grant, revoked, attempts):\n"
        "        await contracts.test_refresh_rotation_and_revoke(live, grant)\n"
        '    assert revoked == {PRIVATE + "old", PRIVATE + "new"}\n'
        '    assert attempts == [PRIVATE + "new", PRIVATE + "old"]\n'
        "async def test_cleanup_continues_after_revoke_failure(monkeypatch):\n"
        "    attempts = []\n"
        "    try:\n"
        "        async with approved_grant(monkeypatch, True) as (_, grant, _, attempts):\n"
        '            grant.tokens = TokenResponse(access_token=PRIVATE + "new",\n'
        '                refresh_token=PRIVATE + "new-refresh", created_at=0, expires_in=600)\n'
        '            grant.pending_revocations.add(PRIVATE + "new")\n'
        "    except pytest.fail.Exception:\n"
        '        assert set(attempts) == {PRIVATE + "old", PRIVATE + "new"}\n'
        "        assert len(attempts) == 2\n"
        '        print("All Trakt token cleanups attempted")\n'
        "        raise\n"
        '    pytest.fail("Cleanup failure was not reported")\n',
        encoding="utf-8",
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-c",
            "pyproject.toml",
            "-q",
            "--tb=long",
            "--showlocals",
            "--noconftest",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
            str(probe),
        ],
        cwd=Path(__file__).resolve().parents[1],
        capture_output=True,
        text=True,
        check=False,
    )
    output = result.stdout + result.stderr
    assert result.returncode == 1
    assert "16 failed, 7 passed" in output
    assert "Trakt stable user uuid missing" in output
    assert "Trakt device-code contract failed" in output
    assert "Trakt transport contract failed" in output
    assert "Trakt pagination headers were not parsed" in output
    assert "Trakt plain-date history did not preserve matching results" in output
    assert "Trakt history was not newest first" in output
    assert "Trakt grant cleanup failed" in output
    assert "All Trakt token cleanups attempted" in output
    assert "synthetic-private-" not in output

"""Opt-in Trakt API v2 contracts, using the real client and in-memory tokens.

Set TASTERR_LIVE_TRAKT_CLIENT_ID and optionally TASTERR_LIVE_TRAKT_CLIENT_SECRET.
TASTERR_LIVE_TRAKT_INTERACTIVE=true permits one device approval, token rotation,
and revocation. The approving account must belong to the development app.
Pagination needs two plays per type; date narrowing needs plays on two UTC dates
per type. These cases skip when their data preconditions are absent.
Only the user code and fixed activation URL are printed during approval.
Community-app-limit status 420 cannot safely be induced; unit tests cover it.
"""

import asyncio
import os
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime, time
from importlib.metadata import version
from time import monotonic

import httpx
import pytest
import pytest_asyncio
from pydantic import TypeAdapter

from tasterr.clients.errors import UpstreamRejected
from tasterr.clients.trakt import HistoryPage, HistoryType, TokenResponse, TraktClient

CLIENT_ID = os.environ.get("TASTERR_LIVE_TRAKT_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TASTERR_LIVE_TRAKT_CLIENT_SECRET") or None
pytestmark = [
    pytest.mark.live,
    pytest.mark.asyncio(loop_scope="module"),
    pytest.mark.skipif(not CLIENT_ID, reason="Trakt client id required"),
]


def _require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message, pytrace=False)


@asynccontextmanager
async def _redacted(message: str) -> AsyncGenerator[None]:
    try:
        yield
        return
    except Exception:
        pass
    # contextlib can restore the original exception; suppress its private payload.
    raise pytest.fail.Exception(message, pytrace=False) from None


@dataclass
class _Live:
    client: TraktClient
    pagination: dict[str, str] = field(default_factory=lambda: dict[str, str]())

    async def history(
        self,
        token: str,
        media_type: HistoryType,
        *,
        page: int = 1,
        limit: int = 250,
        start_at: str | None = None,
    ) -> HistoryPage:
        result = await self.client.history(
            token, media_type, page=page, limit=limit, start_at=start_at
        )
        count = self.pagination.get("X-Pagination-Page-Count")
        applied = self.pagination.get("X-Pagination-Limit")
        current = self.pagination.get("X-Pagination-Page")
        _require(
            result.page_count == (int(count) if count is not None else None)
            and result.page_limit == (int(applied) if applied is not None else None),
            "Trakt pagination headers were not parsed",
        )
        _require(current is None or int(current) == page, "Trakt history page not honoured")
        _require(
            len(result.items) <= (result.page_limit or limit) <= limit,
            "Trakt history limit not honoured",
        )
        dates = [item.watched_at for item in result.items if item.watched_at is not None]
        _require(len(dates) == len(result.items), "Trakt history watched timestamp missing")
        _require(
            all(value.tzinfo is not None for value in dates),
            "Trakt history watched timestamp lacks timezone",
        )
        _require(dates == sorted(dates, reverse=True), "Trakt history was not newest first")
        return result


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def live() -> AsyncGenerator[_Live]:
    async def check_request(request: httpx.Request) -> None:
        oauth = request.url.path.startswith("/oauth/")
        _require(
            request.url.scheme == "https"
            and request.url.host == ("auth.trakt.tv" if oauth else "api.trakt.tv"),
            "Trakt fixed-host contract failed",
        )
        _require(
            request.headers.get("trakt-api-version") == "2"
            and request.headers.get("trakt-api-key") == CLIENT_ID
            and request.headers.get("Content-Type") == "application/json"
            and request.headers.get("User-Agent") == f"Tasterr/{version('tasterr')}",
            "Trakt required-header contract failed",
        )
        if request.url.path == "/oauth/token":
            body = TypeAdapter(dict[str, str]).validate_json(request.content)
            _require(
                body.get("redirect_uri") == "http://localhost",
                "Trakt refresh redirect contract failed",
            )

    async def observe_response(response: httpx.Response) -> None:
        if response.request.url.path.startswith("/sync/history/"):
            state.pagination = {
                key: response.headers[key]
                for key in (
                    "X-Pagination-Page-Count",
                    "X-Pagination-Limit",
                    "X-Pagination-Page",
                )
                if key in response.headers
            }

    async with httpx.AsyncClient(
        timeout=10,
        follow_redirects=False,
        event_hooks={"request": [check_request], "response": [observe_response]},
    ) as http:
        state = _Live(TraktClient(http, CLIENT_ID, CLIENT_SECRET))
        yield state


async def test_device_code_and_required_headers(live: _Live) -> None:
    async with _redacted("Trakt device-code contract failed"):
        code = await live.client.device_code()
        _require(
            bool(code.user_code and code.device_code) and code.interval > 0 and code.expires_in > 0,
            "Trakt device-code fields missing",
        )
        _require(
            "verification_url" not in code.model_dump(),
            "Trakt verification URL was retained",
        )


async def test_immediate_device_poll_is_pending(live: _Live) -> None:
    async with _redacted("Trakt immediate-poll contract failed"):
        code = await live.client.device_code()
        result = await live.client.device_token(code.device_code)
        _require(result == "pending", "Trakt immediate poll was not pending")


@dataclass
class _Grant:
    tokens: TokenResponse = field(repr=False)
    pending_revocations: set[str] = field(default_factory=lambda: set[str](), repr=False)

    def __post_init__(self) -> None:
        self.pending_revocations.add(self.tokens.access_token)


async def _require_revoked(client: TraktClient, token: str) -> None:
    refused = False
    try:
        await client.user_settings(token)
    except UpstreamRejected as error:
        refused = error.status_code in (401, 403)
    _require(refused, "Trakt revoked grant still permits reads")


@pytest_asyncio.fixture(scope="module", loop_scope="module")
async def grant(live: _Live) -> AsyncGenerator[_Grant]:
    if os.environ.get("TASTERR_LIVE_TRAKT_INTERACTIVE") != "true":
        pytest.skip("Explicit Trakt device-approval permission required")
    state: _Grant | None = None
    try:
        async with _redacted("Trakt device-approval contract failed"):
            code = await live.client.device_code()
            print(code.user_code, flush=True)
            print("https://auth.trakt.tv/activate", flush=True)
            deadline = monotonic() + code.expires_in
            interval = code.interval
            while monotonic() + interval < deadline:
                await asyncio.sleep(interval)
                result = await live.client.device_token(code.device_code)
                if isinstance(result, TokenResponse):
                    state = _Grant(result)
                    break
                _require(
                    result in ("pending", "slow_down"),
                    "Trakt device approval was refused or expired",
                )
                if result == "slow_down":
                    interval += 5
            if state is None:
                pytest.fail("Trakt device approval timed out", pytrace=False)
        yield state
    finally:
        if state is not None and state.pending_revocations:
            async with _redacted("Trakt grant cleanup failed"):
                cleaned = True
                for token in tuple(state.pending_revocations):
                    # A token may already be revoked; the follow-up read decides cleanup.
                    with suppress(Exception, pytest.fail.Exception):
                        await live.client.revoke(token)
                    try:
                        await _require_revoked(live.client, token)
                    except (Exception, pytest.fail.Exception):
                        cleaned = False
                    else:
                        state.pending_revocations.remove(token)
                _require(cleaned, "Trakt grant cleanup failed")
                print("Trakt grant cleanup passed")


async def test_user_settings_uuid(live: _Live, grant: _Grant) -> None:
    async with _redacted("Trakt user-settings contract failed"):
        settings = await live.client.user_settings(grant.tokens.access_token)
        _require(bool(settings.user.ids.uuid), "Trakt stable user uuid missing")


async def test_last_activities_watched_fields(live: _Live, grant: _Grant) -> None:
    async with _redacted("Trakt last-activities contract failed"):
        activities = await live.client.last_activities(grant.tokens.access_token)
        _require(
            activities.movies.watched_at is not None and activities.episodes.watched_at is not None,
            "Trakt movie or episode watched activity missing",
        )


@pytest.mark.parametrize("media_type", ["movies", "episodes"])
async def test_history_without_item_id_limits_and_pages(
    live: _Live, grant: _Grant, media_type: HistoryType
) -> None:
    async with _redacted("Trakt history path or pagination contract failed"):
        token = grant.tokens.access_token
        first = await live.history(token, media_type, limit=1)
        second = await live.history(token, media_type, page=2, limit=1)
        combined = await live.history(token, media_type, limit=2)
        _require(
            first.items + second.items == combined.items,
            "Trakt history page or limit not honoured",
        )
        if len(combined.items) < 2:
            pytest.skip("At least two history plays required for deeper pagination")
        _require(bool(first.items and second.items), "Trakt history second page missing")


@pytest.mark.parametrize("media_type", ["movies", "episodes"])
async def test_history_plain_date_narrows_results(
    live: _Live, grant: _Grant, media_type: HistoryType
) -> None:
    async with _redacted("Trakt plain-date history contract failed"):
        token = grant.tokens.access_token
        page_number = 1
        newest_day = None
        samples: list[HistoryPage] = []
        while True:
            sample = await live.history(token, media_type, page=page_number)
            samples.append(sample)
            dates = [item.watched_at for item in sample.items if item.watched_at is not None]
            if newest_day is None and dates:
                newest_day = max(value.astimezone(UTC).date() for value in dates)
            if newest_day is not None and any(
                value.astimezone(UTC).date() < newest_day for value in dates
            ):
                break
            last_page = (
                page_number >= sample.page_count
                if sample.page_count is not None
                else len(sample.items) < (sample.page_limit or 250)
            )
            if last_page:
                pytest.skip("History on at least two UTC dates required for date narrowing")
            page_number += 1
        cutoff = datetime.combine(newest_day, time.min, tzinfo=UTC)
        for page_number, sample in enumerate(samples, 1):
            narrowed = await live.history(
                token, media_type, page=page_number, start_at=newest_day.isoformat()
            )
            expected = [
                item
                for item in sample.items
                if item.watched_at is not None and item.watched_at >= cutoff
            ]
            _require(
                narrowed.items == expected,
                "Trakt plain-date history did not preserve matching results",
            )
        first = await live.history(token, media_type, limit=1, start_at=newest_day.isoformat())
        _require(
            bool(first.items)
            and all(
                item.watched_at is not None and item.watched_at >= cutoff for item in first.items
            ),
            "Trakt plain-date history lost matching results",
        )


async def test_refresh_rotation_and_revoke(live: _Live, grant: _Grant) -> None:
    async with _redacted("Trakt refresh or revoke contract failed"):
        previous = grant.tokens
        grant.tokens = await live.client.refresh(previous.refresh_token)
        grant.pending_revocations.add(grant.tokens.access_token)
        _require(
            grant.tokens.access_token != previous.access_token
            and grant.tokens.refresh_token != previous.refresh_token,
            "Trakt refresh did not rotate the token pair",
        )
        await live.client.user_settings(grant.tokens.access_token)
        await live.client.revoke(grant.tokens.access_token)
        await _require_revoked(live.client, grant.tokens.access_token)
        grant.pending_revocations.remove(grant.tokens.access_token)

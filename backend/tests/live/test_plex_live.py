"""Opt-in Plex contracts for an owner, managed user, and shared user.

Set these variables locally, then run ``just test-live``:

    TASTERR_LIVE_PLEX_OWNER_TOKEN
    TASTERR_LIVE_PLEX_MANAGED_TOKEN
    TASTERR_LIVE_PLEX_SHARED_TOKEN

The suite is read-only. It never prints tokens, URLs, account/server identifiers,
rating keys, titles, timestamps, or raw upstream bodies.
"""

import os
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

import httpx
import pytest
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from tasterr.auth.crypto import plex_client_identifier
from tasterr.catalog.models import MAX_TMDB_ID
from tasterr.clients.errors import UpstreamError
from tasterr.clients.plex import (
    PRODUCT,
    RESOURCES_URL,
    PlexCloudAccount,
    PlexMediaClient,
    PlexPmsItem,
    PlexServer,
)

pytestmark = pytest.mark.live

TOKENS = (
    ("owner", os.environ.get("TASTERR_LIVE_PLEX_OWNER_TOKEN", "")),
    ("managed", os.environ.get("TASTERR_LIVE_PLEX_MANAGED_TOKEN", "")),
    ("shared", os.environ.get("TASTERR_LIVE_PLEX_SHARED_TOKEN", "")),
)
CLIENT_ID = plex_client_identifier("tasterr-live-plex-contracts")
HISTORY_DAYS = 365
GUID_CANDIDATE_MAX = 20

requires_roles = pytest.mark.skipif(
    not all(token for _role, token in TOKENS),
    reason=("TASTERR_LIVE_PLEX_OWNER_TOKEN/MANAGED_TOKEN/SHARED_TOKEN must all be set"),
)


class _ResourceShape(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    client_identifier: str = Field(alias="clientIdentifier", min_length=1)
    owned: bool = False
    provides: str = ""


class _HistoryContainer(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    offset: int | None = None
    items: list[PlexPmsItem] = Field(default_factory=lambda: list[PlexPmsItem](), alias="Metadata")


class _HistoryEnvelope(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)

    media_container: _HistoryContainer = Field(alias="MediaContainer")


@dataclass(frozen=True)
class _RoleState:
    role: str
    token: str
    account: PlexCloudAccount
    server: PlexServer
    account_id: int
    history: tuple[PlexPmsItem, ...]
    continue_watching: tuple[PlexPmsItem, ...]


_states: tuple[_RoleState, ...] | None = None


def _require(condition: bool, message: str) -> None:
    if not condition:
        pytest.fail(message, pytrace=False)


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/json",
        "X-Plex-Product": PRODUCT,
        "X-Plex-Client-Identifier": CLIENT_ID,
        "X-Plex-Token": token,
    }


async def _load_states() -> tuple[_RoleState, ...]:
    global _states
    if _states is not None:
        return _states

    viewed_before = int(datetime.now(UTC).timestamp())
    viewed_after = int((datetime.now(UTC) - timedelta(days=HISTORY_DAYS)).timestamp())
    loaded: list[_RoleState] = []
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as http:
        client = PlexMediaClient(http, CLIENT_ID)
        for role, token in TOKENS:
            try:
                account = await client.account(token)
            except UpstreamError:
                pytest.fail(f"{role} account contract failed", pytrace=False)
            try:
                servers = await client.servers(token)
            except UpstreamError:
                pytest.fail(f"{role} resource contract failed", pytrace=False)
            _require(bool(servers), f"{role} has no verified Plex server")
            selected: tuple[PlexServer, int, list[PlexPmsItem], list[PlexPmsItem]] | None = None
            failure_phases: list[str] = []
            for server in servers:
                try:
                    account_id = await client.resolve_account_id(server, account)
                except UpstreamError:
                    failure_phases.append("local-account")
                    continue
                try:
                    history = await client.history(
                        server,
                        account_id,
                        viewed_after=viewed_after,
                        viewed_before=viewed_before,
                    )
                except UpstreamError:
                    failure_phases.append("history")
                    continue
                try:
                    continue_watching = await client.continue_watching(server)
                except UpstreamError:
                    failure_phases.append("continue-watching")
                    continue
                selected = (server, account_id, history, continue_watching)
                break
            if selected is None:
                phases = ", ".join(sorted(set(failure_phases))) or "unknown"
                pytest.fail(
                    f"{role} had no account-scoped readable Plex server; phases: {phases}",
                    pytrace=False,
                )
            server, account_id, history, continue_watching = selected
            loaded.append(
                _RoleState(
                    role=role,
                    token=token,
                    account=account,
                    server=server,
                    account_id=account_id,
                    history=tuple(history),
                    continue_watching=tuple(continue_watching),
                )
            )
    _states = tuple(loaded)
    return _states


def _resource_ids(payload: object) -> tuple[str, ...]:
    if not isinstance(payload, list):
        pytest.fail("unexpected Plex resource response shape", pytrace=False)
    try:
        resources = [_ResourceShape.model_validate(item) for item in cast("list[object]", payload)]
    except ValidationError:
        pytest.fail("unexpected Plex resource response shape", pytrace=False)
    servers = [item for item in resources if "server" in item.provides.split(",")]
    servers.sort(key=lambda item: (not item.owned, item.client_identifier))
    return tuple(item.client_identifier for item in servers)


def _history_page(response: httpx.Response) -> _HistoryContainer:
    _require(response.status_code == 200, "Plex history page request failed")
    try:
        return _HistoryEnvelope.model_validate(response.json()).media_container
    except (ValueError, ValidationError):
        pytest.fail("unexpected Plex history response shape", pytrace=False)


def _rating_key(value: int | str | None) -> str | None:
    raw = str(value) if value is not None else ""
    return raw if raw.isdecimal() and int(raw) > 0 else None


def _tmdb_guid(item: PlexPmsItem | None) -> int | None:
    if item is None:
        return None
    for guid in item.guids:
        raw = guid.id.removeprefix("tmdb://") if guid.id.startswith("tmdb://") else ""
        if raw.isdecimal() and 1 <= int(raw) <= MAX_TMDB_ID:
            return int(raw)
    return None


@requires_roles
async def test_tokens_resources_tls_identity_and_local_accounts() -> None:
    states = await _load_states()

    _require(len(states) == 3, "all three Plex roles were not validated")
    _require(
        len({state.server.access_token.get_secret_value() for state in states}) == 3,
        "Plex roles did not receive distinct server-scoped tokens",
    )
    for state in states:
        _require(state.account.id > 0, f"{state.role} cloud account was invalid")
        _require(state.account_id > 0, f"{state.role} PMS account resolution failed")
        _require(
            state.server.base_url.startswith("https://")
            and ".plex.direct:" in state.server.base_url,
            f"{state.role} server did not use an allowlisted HTTPS connection",
        )

    versions = sorted(
        {state.server.version for state in states if state.server.version is not None}
    )
    _require(bool(versions), "verified Plex servers did not expose a version")
    print(f"\nPlex PMS versions tested: {', '.join(versions)}")


@requires_roles
async def test_resources_are_unpaged_and_selection_is_deterministic() -> None:
    states = await _load_states()
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as http:
        for state in states:
            params = {"includeHttps": "1", "includeRelay": "1", "includeIPv6": "1"}
            first_headers = _headers(state.token) | {
                "X-Plex-Container-Start": "0",
                "X-Plex-Container-Size": "1",
            }
            second_headers = _headers(state.token) | {
                "X-Plex-Container-Start": "1",
                "X-Plex-Container-Size": "1",
            }
            try:
                first = await http.get(RESOURCES_URL, params=params, headers=first_headers)
                second = await http.get(RESOURCES_URL, params=params, headers=second_headers)
            except httpx.HTTPError:
                pytest.fail(f"{state.role} resource transport failed", pytrace=False)
            _require(
                first.status_code == 200 and second.status_code == 200,
                f"{state.role} resource discovery failed",
            )
            _require(
                not any(key.lower().startswith("x-plex-container-") for key in first.headers),
                f"{state.role} resource response unexpectedly advertised paging",
            )
            first_ids = _resource_ids(first.json())
            second_ids = _resource_ids(second.json())
            _require(first_ids == second_ids, f"{state.role} resources unexpectedly paged")
            _require(
                state.server.machine_identifier in first_ids[:4],
                f"{state.role} selected server was outside the bounded deterministic set",
            )


@requires_roles
async def test_history_is_account_filtered_isolated_and_paged() -> None:
    states = await _load_states()
    histories: list[set[tuple[str, str, int]]] = []
    paged_roles = 0
    now = int(datetime.now(UTC).timestamp())
    after = int((datetime.now(UTC) - timedelta(days=HISTORY_DAYS)).timestamp())

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as http:
        for state in states:
            _require(bool(state.history), f"{state.role} has no seeded Plex history")
            _require(
                all(item.account_id == state.account_id for item in state.history),
                f"{state.role} history contained another account",
            )
            fingerprints = {
                (item.media_type, str(item.rating_key), item.viewed_at)
                for item in state.history
                if item.viewed_at is not None
            }
            _require(bool(fingerprints), f"{state.role} history lacked merge timestamps")
            histories.append(fingerprints)

            params = {
                "accountID": str(state.account_id),
                "sort": "viewedAt:desc",
                "viewedAt>": str(after),
                "viewedAt<": str(now),
            }
            headers = _headers(state.server.access_token.get_secret_value())
            try:
                first = await http.get(
                    f"{state.server.base_url}/status/sessions/history/all",
                    params=params,
                    headers=headers | {"X-Plex-Container-Start": "0", "X-Plex-Container-Size": "1"},
                )
                second = await http.get(
                    f"{state.server.base_url}/status/sessions/history/all",
                    params=params,
                    headers=headers | {"X-Plex-Container-Start": "1", "X-Plex-Container-Size": "1"},
                )
            except httpx.HTTPError:
                pytest.fail(f"{state.role} history transport failed", pytrace=False)
            first_page = _history_page(first)
            second_page = _history_page(second)
            _require(first_page.offset in (None, 0), f"{state.role} first history offset failed")
            _require(
                all(item.account_id == state.account_id for item in first_page.items),
                f"{state.role} first history page crossed accounts",
            )
            _require(
                all(item.account_id == state.account_id for item in second_page.items),
                f"{state.role} second history page crossed accounts",
            )
            if second_page.items:
                paged_roles += 1
                _require(
                    second_page.offset in (None, 1),
                    f"{state.role} second history offset failed",
                )
                first_time = first_page.items[0].viewed_at if first_page.items else None
                second_time = second_page.items[0].viewed_at
                _require(
                    first_time is not None
                    and second_time is not None
                    and first_time >= second_time,
                    f"{state.role} history pages were not newest-first",
                )

    _require(paged_roles > 0, "no Plex role had a live second history page")
    for index, own in enumerate(histories):
        others = {item for other, rows in enumerate(histories) if other != index for item in rows}
        _require(bool(own - others), "a Plex role lacked an isolated history row")


@requires_roles
async def test_continue_watching_is_role_scoped_and_reports_next_up_sources() -> None:
    states = await _load_states()
    fingerprints: list[set[tuple[str, str]]] = []
    next_up_sources: set[str] = set()
    for state in states:
        _require(bool(state.continue_watching), f"{state.role} has no seeded Continue Watching")
        rows: set[tuple[str, str]] = set()
        for item in state.continue_watching:
            has_progress = isinstance(item.view_offset, (int, float)) and isinstance(
                item.duration, (int, float)
            )
            next_up = item.media_type == "episode" and "view_offset" not in item.model_fields_set
            if not has_progress and not next_up:
                continue
            if next_up:
                next_up_sources.add(
                    "lastViewedAt"
                    if item.last_viewed_at is not None
                    else "grandparentLastViewedAt"
                    if item.grandparent_last_viewed_at is not None
                    else "parentLastViewedAt"
                    if item.parent_last_viewed_at is not None
                    else "hub-position fallback"
                )
            rows.add((item.media_type, str(item.rating_key)))
        _require(bool(rows), f"{state.role} Continue Watching lacked eligible rows")
        fingerprints.append(rows)

    for index, own in enumerate(fingerprints):
        others = {
            item for other, rows in enumerate(fingerprints) if other != index for item in rows
        }
        _require(bool(own - others), "a Plex role lacked an isolated Continue Watching row")
    print(
        "Continue Watching next-up ordering sources: "
        + (", ".join(sorted(next_up_sources)) if next_up_sources else "not exercised")
    )


@requires_roles
async def test_movie_and_episode_to_show_guid_mapping() -> None:
    states = await _load_states()
    movie_mapped = False
    show_mapped = False
    checked = 0

    async with httpx.AsyncClient(timeout=10.0, follow_redirects=False) as http:
        client = PlexMediaClient(http, CLIENT_ID)
        for state in states:
            candidates = (*state.history, *state.continue_watching)
            for item in candidates:
                if checked >= GUID_CANDIDATE_MAX or (movie_mapped and show_mapped):
                    break
                checked += 1
                try:
                    if item.media_type == "movie" and not movie_mapped:
                        key = _rating_key(item.rating_key)
                        movie_mapped = (
                            key is not None
                            and _tmdb_guid(await client.metadata(state.server, key)) is not None
                        )
                    elif item.media_type == "episode" and not show_mapped:
                        show_key = _rating_key(item.grandparent_rating_key)
                        if show_key is None:
                            episode_key = _rating_key(item.rating_key)
                            episode = (
                                await client.metadata(state.server, episode_key)
                                if episode_key is not None
                                else None
                            )
                            show_key = _rating_key(
                                episode.grandparent_rating_key if episode is not None else None
                            )
                        show_mapped = (
                            show_key is not None
                            and _tmdb_guid(await client.metadata(state.server, show_key))
                            is not None
                        )
                except UpstreamError:
                    pytest.fail(f"{state.role} metadata contract failed", pytrace=False)
            if movie_mapped and show_mapped:
                break

    _require(movie_mapped, "no bounded live movie resolved a TMDB GUID")
    _require(show_mapped, "no bounded live episode resolved its show's TMDB GUID")

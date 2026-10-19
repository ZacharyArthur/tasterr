"""Opt-in Jellyfin contracts; disposable users are always deleted in teardown.

Set TASTERR_LIVE_JELLYFIN_URL, TASTERR_LIVE_JELLYFIN_API_KEY and explicitly
TASTERR_LIVE_JELLYFIN_DISPOSABLE_USERS=true to permit account creation/deletion.
TASTERR_LIVE_JELLYFIN_USER_ID must name a user with at least two played movies and
two played episodes, with distinct play dates per type, for the ordering contract.
No live values or upstream bodies are printed.
"""

# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
import os
import uuid
from collections.abc import AsyncGenerator

import httpx
import pytest

from tasterr.clients.errors import UpstreamRejected
from tasterr.clients.jellyfin import JellyfinClient, JellyfinUser

URL = os.environ.get("TASTERR_LIVE_JELLYFIN_URL", "").rstrip("/")
KEY = os.environ.get("TASTERR_LIVE_JELLYFIN_API_KEY", "")
HISTORY_USER = os.environ.get("TASTERR_LIVE_JELLYFIN_USER_ID", "")
pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(not (URL and KEY), reason="Jellyfin coordinates required"),
]
DEVICE_ID = "tasterr-live-contract"
PASSWORD = "Disposable-contract-" + uuid.uuid4().hex


def headers(token: str) -> dict[str, str]:
    return {
        "Authorization": 'MediaBrowser Client="Tasterr contracts", Device="Contracts", '
        f'DeviceId="{DEVICE_ID}", Version="1", Token="{token}"'
    }


@pytest.fixture
async def disposable_users() -> AsyncGenerator[tuple[httpx.AsyncClient, list[JellyfinUser]]]:
    if os.environ.get("TASTERR_LIVE_JELLYFIN_DISPOSABLE_USERS") != "true":
        pytest.skip("Explicit disposable-user permission required")
    users: list[JellyfinUser] = []
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
        try:
            for index in range(4):
                response = await http.post(
                    f"{URL}/Users/New",
                    headers=headers(KEY),
                    json={"Name": "tasterr-contract-" + uuid.uuid4().hex},
                )
                assert response.status_code == 200
                user = JellyfinUser.model_validate(response.json())
                users.append(user)
                if index != 2:
                    response = await http.post(
                        f"{URL}/Users/{user.id}/Password",
                        headers=headers(KEY),
                        json={"CurrentPw": "", "NewPw": PASSWORD, "ResetPassword": False},
                    )
                    assert response.status_code in (200, 204)
            yield http, users
        finally:
            for user in users:
                response = await http.delete(f"{URL}/Users/{user.id}", headers=headers(KEY))
                assert response.status_code in (200, 204, 404)


async def test_version_recorded() -> None:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
        response = await http.get(f"{URL}/System/Info/Public")
        assert response.status_code == 200
        version = response.json()["Version"]
        assert isinstance(version, str) and version
        print(f"Jellyfin version tested: {version}")


async def test_auth_logout_policy_empty_password_and_shared_device(
    disposable_users: tuple[httpx.AsyncClient, list[JellyfinUser]],
) -> None:
    http, users = disposable_users
    client = JellyfinClient(http, URL, KEY, DEVICE_ID)
    first = await client.authenticate(users[0].name, PASSWORD)
    second = await client.authenticate(users[1].name, PASSWORD)
    assert first.user.id == users[0].id and second.user.id == users[1].id
    await client.logout(first.access_token)
    response = await http.get(f"{URL}/Users/Me", headers=headers(second.access_token))
    assert response.status_code == 200
    assert response.json()["Id"] == users[1].id
    await client.logout(second.access_token)
    for token in (first.access_token, second.access_token):
        assert (await http.get(f"{URL}/Users/Me", headers=headers(token))).status_code == 401
    empty = await client.authenticate(users[2].name, "")
    await client.logout(empty.access_token)
    user = await client.user(users[0].id)
    assert user.policy.is_administrator is False and user.policy.is_disabled is False


async def test_lockout_and_deleted_user_404(
    disposable_users: tuple[httpx.AsyncClient, list[JellyfinUser]],
) -> None:
    http, users = disposable_users
    client = JellyfinClient(http, URL, KEY, DEVICE_ID)
    user = users[3]
    response = await http.get(f"{URL}/Users/{user.id}", headers=headers(KEY))
    policy = response.json()["Policy"]
    policy["LoginAttemptsBeforeLockout"] = 3
    policy["InvalidLoginAttemptCount"] = 0
    response = await http.post(f"{URL}/Users/{user.id}/Policy", headers=headers(KEY), json=policy)
    assert response.status_code in (200, 204)
    response = await http.get(f"{URL}/Users/{user.id}", headers=headers(KEY))
    assert response.status_code == 200
    assert response.json()["Policy"]["LoginAttemptsBeforeLockout"] == 3
    for _ in range(3):
        with pytest.raises(UpstreamRejected):
            await client.authenticate(user.name, "incorrect-contract-password")
    assert (await client.user(user.id)).policy.is_disabled
    with pytest.raises(UpstreamRejected):
        await client.authenticate(user.name, PASSWORD)
    assert (await http.delete(f"{URL}/Users/{user.id}", headers=headers(KEY))).status_code in (
        200,
        204,
    )
    with pytest.raises(UpstreamRejected) as failure:
        await client.user(user.id)
    assert failure.value.status_code == 404


@pytest.mark.skipif(not HISTORY_USER, reason="A user with played movies and episodes is required")
async def test_played_items_and_series_provider_ids() -> None:
    async with httpx.AsyncClient(timeout=10, follow_redirects=False) as http:
        client = JellyfinClient(http, URL, KEY, DEVICE_ID)
        movies = await client.played_items(HISTORY_USER, "Movie", 0)
        episodes = await client.played_items(HISTORY_USER, "Episode", 0)
        assert movies.items and episodes.items
        for page in (movies, episodes):
            dates = [
                item.user_data.last_played_date
                for item in page.items
                if item.user_data and item.user_data.last_played_date
            ]
            assert len(set(dates)) >= 2
            assert dates == sorted(dates, reverse=True)
        assert any(item.provider_ids.get("Tmdb") for item in movies.items)
        assert any(item.user_data and item.user_data.last_played_date for item in movies.items)
        ids = list(dict.fromkeys(item.series_id for item in episodes.items if item.series_id))
        assert ids
        series = await client.series(HISTORY_USER, ids)
        assert series.items and any(item.provider_ids.get("Tmdb") for item in series.items)

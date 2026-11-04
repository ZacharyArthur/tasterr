import asyncio
import time
from datetime import timedelta
from pathlib import Path
from typing import cast

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.test_auth_api import SECRET
from tests.trakt_fixtures import FakeTrakt, entry, trakt_harness

from tasterr.auth.crypto import decrypt_token, encrypt_token
from tasterr.auth.login import derive_admin, get_link
from tasterr.auth.pins import PinStore
from tasterr.auth.ratelimit import TokenBucket
from tasterr.auth.sessions import mint_session
from tasterr.auth.trakt import DeviceAttempt, TraktCredential
from tasterr.db.models import LinkedAccount, Profile, User, UserSession, utcnow
from tasterr.recommend import store
from tasterr.runtime_settings import RuntimeSettings


async def test_trakt_never_supplies_admin_display_or_seerr_authentication(tmp_path: Path) -> None:
    from tests.test_account_api import LOCAL

    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None
            assert not await derive_admin(
                [link],
                True,
                None,
                secret_key=SECRET,
                plex=None,
                server_id=None,
                plex_resources=None,
            )
        response = await fixture.client.post("/api/v1/auth/local", json=LOCAL)
        assert response.status_code == 200 and response.json()["display_name"] == "Viewer"
        assert (
            await fixture.client.post("/api/v1/account/links/seerr", json={"method": "trakt"})
        ).status_code == 422
        assert (await fixture.client.post("/api/v1/auth/trakt", json={})).status_code in (404, 405)


async def test_browser_headers_never_forwarded_upstream_and_upstream_headers_stay_private(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = FakeTrakt.respond

    async def respond(fake: FakeTrakt, request: httpx.Request) -> httpx.Response:
        assert "x-browser-fixture" not in request.headers
        response = await original(fake, request)
        response.headers["X-Upstream-Fixture"] = "private-fixture"
        return response

    monkeypatch.setattr(FakeTrakt, "respond", respond)
    async with trakt_harness(tmp_path) as fixture:
        response = await fixture.client.post(
            "/api/v1/account/links/trakt/device", headers={"X-Browser-Fixture": "private-browser"}
        )
        assert response.status_code == 200
        assert "x-upstream-fixture" not in response.headers
        assert "private-fixture" not in response.text and "client-fixture" not in response.text


async def test_device_and_poll_enforce_mutation_bucket_before_upstream_calls(
    tmp_path: Path,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        fixture.app.state.mutation_bucket = TokenBucket(capacity=1, refill_per_second=0)
        handle = await fixture.create_handle()
        count = len(fixture.upstream.requests)
        assert (await fixture.client.post("/api/v1/account/links/trakt/device")).status_code == 429
        assert (await fixture.poll(handle)).status_code == 429
        assert len(fixture.upstream.requests) == count


async def test_sign_in_exclusions_admin_counts_and_last_usable_link(tmp_path: Path) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        fixture.settings.plex_server_id = "pinned"
        async with fixture.maker() as db:
            link = await get_link(db, 1, "seerr")
            assert link is not None
            await db.delete(link)
            db.add(
                LinkedAccount(
                    user_id=1, provider="plex", external_id="plex-fixture", display_name="Plex"
                )
            )
            await db.commit()
        response = await fixture.client.get("/api/v1/settings")
        assert response.status_code == 200
        assert response.json()["sign_in_link_counts"] == [{"methods": ["plex"], "count": 1}]
        invalid = RuntimeSettings().model_dump(mode="json")
        invalid["disabled_sign_in_methods"] = ["trakt"]
        assert (await fixture.client.put("/api/v1/settings", json=invalid)).status_code == 422
        assert (await fixture.client.get("/api/v1/settings")).json()["settings"][
            "disabled_sign_in_methods"
        ] == []
        assert (
            await fixture.client.post("/api/v1/account/links/plex/unlink", json={})
        ).status_code == 409
        assert (
            await fixture.client.post("/api/v1/account/links/trakt/unlink", json={})
        ).status_code == 204


@pytest.mark.parametrize("other_owner", [False, True])
async def test_link_conflicts_consume_handle_without_mutating_existing_links(
    tmp_path: Path, other_owner: bool
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        if other_owner:
            async with fixture.maker() as db:
                db.add(User(id=2, display_name="Other private member"))
                await db.flush()
                db.add(
                    LinkedAccount(
                        user_id=2,
                        provider="trakt",
                        external_id=fixture.upstream.uuid,
                        display_name="Other",
                    )
                )
                await db.commit()
        else:
            await fixture.seed()
            fixture.upstream.uuid = "different-uuid"
        handle = await fixture.create_handle()
        response = await fixture.poll(handle)
        assert response.status_code == 409 and "Other private member" not in response.text
        assert (await fixture.poll(handle)).status_code == 404
        async with fixture.maker() as db:
            links = list(
                await db.scalars(select(LinkedAccount).where(LinkedAccount.provider == "trakt"))
            )
            assert len(links) == 1
            assert links[0].external_id == "stable-fixture-uuid"


@pytest.mark.parametrize("expiry", [30, 6000])
async def test_foreign_session_preserves_handle_and_server_ttl(tmp_path: Path, expiry: int) -> None:
    async with trakt_harness(tmp_path) as fixture:
        fixture.upstream.expires_in = expiry
        handle = await fixture.create_handle()
        original = fixture.client.cookies.get("tasterr_session")
        assert original is not None
        async with fixture.maker() as db:
            foreign = await mint_session(db, 1)
            await db.commit()
        fixture.client.cookies.clear()
        fixture.client.cookies.set("tasterr_session", foreign)
        assert (await fixture.poll(handle)).status_code == 404
        fixture.client.cookies.clear()
        fixture.client.cookies.set("tasterr_session", original)
        pins = cast("PinStore[DeviceAttempt]", fixture.app.state.trakt_pin_store)
        pending = pins._pending[handle]  # pyright: ignore[reportPrivateUsage]
        assert pending.expires == pending.created + min(expiry, 600)
        assert (await fixture.poll(handle)).status_code == 200


async def test_poll_is_exempt_from_login_bucket(tmp_path: Path) -> None:
    async with trakt_harness(tmp_path) as fixture:
        handle = await fixture.create_handle()
        fixture.upstream.poll_status = 400
        for _ in range(12):
            assert (await fixture.poll(handle)).status_code == 200
        for _ in range(20):
            response = await fixture.client.post("/api/v1/account/links/trakt/device")
            if response.status_code == 429:
                break
        else:
            raise AssertionError("device creation must use the login bucket")
        assert response.status_code == 429


@pytest.mark.parametrize("action", ["unlink", "delete"])
async def test_hanging_revoke_is_bounded_after_local_commit(tmp_path: Path, action: str) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()

        async def hang(_token: str) -> None:
            async with fixture.maker() as db:
                assert await get_link(db, 1, "trakt") is None
            await asyncio.Event().wait()

        fixture.upstream.on_revoke = hang
        path = (
            "/api/v1/account/links/trakt/unlink" if action == "unlink" else "/api/v1/account/delete"
        )
        started = time.monotonic()
        async with asyncio.timeout(6):
            response = await fixture.client.post(
                path, json={"confirm": "Viewer"} if action == "delete" else {}
            )
        assert response.status_code == 204 and time.monotonic() - started < 6


async def test_unlink_with_history_deletes_only_trakt_and_invalidates_profile(
    tmp_path: Path,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        async with fixture.maker() as db:
            await store.record_signal(db, 1, "movie", 550, "watched_trakt")
            await store.record_signal(db, 1, "movie", 550, "watched_plex")
            db.add(Profile(user_id=1, vector="{}"))
            await db.commit()
        response = await fixture.client.post(
            "/api/v1/account/links/trakt/unlink", json={"delete_history": True}
        )
        assert response.status_code == 204
        async with fixture.maker() as db:
            assert [row.kind for row in await store.load_signals(db, 1)] == ["watched_plex"]
            assert await db.get(Profile, 1) is None


async def test_link_summary_encryption_identity_and_relink(tmp_path: Path) -> None:
    async with trakt_harness(tmp_path) as fixture:
        handle = await fixture.create_handle()
        early = await fixture.client.post(
            "/api/v1/account/links/trakt/device/poll", json={"handle": handle}
        )
        assert early.json()["status"] == "pending"
        assert not any(r.url.path == "/oauth/device/token" for r in fixture.upstream.requests)
        response = await fixture.poll(handle)
        assert response.status_code == 200 and response.json()["status"] == "linked"
        assert "access" not in response.text and "uuid" not in response.text
        provider = next(
            p for p in response.json()["account"]["providers"] if p["provider"] == "trakt"
        )
        assert (
            provider["linked"]
            and provider["available"]
            and provider["can_unlink"]
            and not provider["sign_in"]
        )
        assert (await fixture.poll(handle)).status_code == 404
        await asyncio.gather(*fixture.app.state.trakt_history_tasks.values())
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert (
                link is not None
                and link.external_id == fixture.upstream.uuid
                and link.avatar_url is None
            )
            assert link.credential_enc and "device-access" not in link.credential_enc
            credential = TraktCredential.model_validate_json(
                decrypt_token(SECRET, link.credential_enc)
            )
            assert credential.access_token == "device-access"
            assert "access" not in str((await db.scalars(select(UserSession))).all()[0].__dict__)
            assert (await db.get(User, 1)).display_name == "Viewer"  # pyright: ignore[reportOptionalMemberAccess]
        fixture.upstream.username = "New Trakt name"
        assert (await fixture.poll(await fixture.create_handle())).status_code == 200
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.display_name == "New Trakt name"
        assert set((await fixture.client.get("/api/v1/auth/methods")).json()) == {
            "plex",
            "jellyfin",
            "seerr",
        }


@pytest.mark.parametrize("throttled", [False, True])
async def test_relink_preserves_sync_state_and_cleared_history(
    tmp_path: Path, throttled: bool
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        synced = utcnow() - timedelta(hours=1)
        attempted = utcnow() - timedelta(hours=1 if throttled else 7)
        await fixture.seed(synced=synced)
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None
            link.sync_attempted_at = attempted
            await store.record_signal(
                db, 1, "movie", 550, "watched_trakt", utcnow() - timedelta(days=1095)
            )
            await db.commit()
        assert (
            await fixture.client.post("/api/v1/account/taste-sources/trakt/clear")
        ).status_code == 204
        fixture.upstream.pages = {("movies", 1): [entry(550, days=1095)]}
        fixture.upstream.username = "Updated Trakt name"
        response = await fixture.poll(await fixture.create_handle())
        assert response.status_code == 200 and response.json()["status"] == "linked"
        await asyncio.gather(*fixture.app.state.trakt_history_tasks.values())
        reads = [
            request
            for request in fixture.upstream.requests
            if request.url.path.startswith("/sync/history/")
        ]
        if throttled:
            assert not reads
        else:
            assert len(reads) == 2
            assert all(
                request.url.params.get("start_at")
                == (synced - timedelta(days=1)).date().isoformat()
                for request in reads
            )
        async with fixture.maker() as db:
            assert not await store.load_signals(db, 1)
            link = await get_link(db, 1, "trakt")
            assert link is not None and link.credential_enc is not None
            assert link.display_name == "Updated Trakt name"
            credential = TraktCredential.model_validate_json(
                decrypt_token(SECRET, link.credential_enc)
            )
            assert credential.access_token == "device-access"
            assert credential.refresh_token == "device-refresh"
            if throttled:
                assert link.sync_attempted_at == attempted and link.sync_synced_at == synced
            else:
                assert link.sync_attempted_at is not None and link.sync_attempted_at > attempted
                assert link.sync_synced_at is not None and link.sync_synced_at >= synced


@pytest.mark.parametrize(
    "status,outcome",
    [
        (400, "pending"),
        (404, "expired"),
        (409, "expired"),
        (410, "expired"),
        (418, "denied"),
        (420, "denied"),
        (429, "pending"),
    ],
)
async def test_poll_states_and_slowdown(tmp_path: Path, status: int, outcome: str) -> None:
    async with trakt_harness(tmp_path) as fixture:
        handle = await fixture.create_handle()
        fixture.upstream.poll_status = status
        response = await fixture.poll(handle)
        assert response.json()["status"] == outcome
        if status == 429:
            assert response.json()["interval"] == 11
        if outcome not in ("pending",):
            assert (await fixture.poll(handle)).status_code == 404
        async with fixture.maker() as db:
            assert await get_link(db, 1, "trakt") is None


@pytest.mark.parametrize("failure", ["poll", "settings", "commit"])
async def test_transient_poll_keeps_handle_but_post_exchange_failures_consume_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        handle = await fixture.create_handle()
        commit_failed = False
        if failure == "poll":
            fixture.upstream.poll_status = 503
        elif failure == "settings":
            fixture.upstream.settings_status = 503
        else:
            original = AsyncSession.commit

            async def fail_commit(db: AsyncSession) -> None:
                nonlocal commit_failed
                link_id = await db.scalar(
                    select(LinkedAccount.id).where(LinkedAccount.provider == "trakt")
                )
                if link_id is not None:
                    commit_failed = True
                    raise RuntimeError("fixture commit failed")
                await original(db)

            monkeypatch.setattr(AsyncSession, "commit", fail_commit)
        assert (await fixture.poll(handle)).status_code == 502
        assert commit_failed is (failure == "commit")
        async with fixture.maker() as db:
            assert await get_link(db, 1, "trakt") is None
        if failure == "poll":
            fixture.upstream.poll_status = 200
            assert (await fixture.poll(handle)).status_code == 200
        else:
            assert (await fixture.poll(handle)).status_code == 404


async def test_session_flow_isolation_expiry_and_guards(tmp_path: Path) -> None:
    async with trakt_harness(tmp_path) as fixture:
        assert (
            await fixture.client.post(
                "/api/v1/account/links/trakt/device", headers={"Origin": "https://foreign.invalid"}
            )
        ).status_code == 403
        handle = await fixture.create_handle()
        cookie = fixture.client.cookies.get("tasterr_session")
        response = await fixture.client.post(
            "/api/v1/account/links/plex/pin/poll", json={"pin_id": handle}
        )
        assert response.status_code == 404
        plex = (await fixture.client.post("/api/v1/account/links/plex/pin")).json()["pin_id"]
        assert (await fixture.poll(plex)).status_code == 404
        fixture.client.cookies.clear()
        assert (await fixture.poll(handle)).status_code == 401
        if cookie:
            fixture.client.cookies.set("tasterr_session", cookie)
        # The original session retains its attempt after an unauthenticated poll.
        pins = cast("PinStore[DeviceAttempt]", fixture.app.state.trakt_pin_store)
        pending = pins._pending[handle]  # pyright: ignore[reportPrivateUsage]
        assert pending.expires == pending.created + 600
        pending.expires = time.monotonic() - 1
        assert (await fixture.poll(handle)).status_code == 404
        fixture.settings.trakt_client_id = None
        assert (await fixture.client.post("/api/v1/account/links/trakt/device")).status_code == 503


@pytest.mark.parametrize("action", ["unlink", "delete"])
@pytest.mark.parametrize("blob", ["undecryptable", "malformed", "expired", "valid", "dormant"])
async def test_revoke_after_commit_is_best_effort_and_bad_credentials_do_not_block(
    tmp_path: Path,
    action: str,
    blob: str,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed(expires=-1 if blob == "expired" else 3600)
        async with fixture.maker() as db:
            link = await get_link(db, 1, "trakt")
            assert link is not None
            if blob == "undecryptable":
                link.credential_enc = "broken"
            if blob == "malformed":
                link.credential_enc = encrypt_token(SECRET, "not JSON")
            await store.record_signal(db, 1, "movie", 550, "watched_trakt")
            db.add(Profile(user_id=1, vector="{}"))
            await db.commit()
        if blob == "dormant":
            fixture.settings.trakt_client_id = None
        revoked: list[str] = []

        async def revoke(token: str) -> None:
            async with fixture.maker() as db:
                assert await get_link(db, 1, "trakt") is None
            revoked.append(token)

        fixture.upstream.on_revoke = revoke
        fixture.upstream.revoke_status = 503
        path = (
            "/api/v1/account/links/trakt/unlink" if action == "unlink" else "/api/v1/account/delete"
        )
        response = await fixture.client.post(
            path, json={} if action == "unlink" else {"confirm": "Viewer"}
        )
        assert response.status_code == 204
        assert revoked == (["original-access"] if blob in ("valid", "expired") else [])
        assert not any(r.url.path == "/oauth/token" for r in fixture.upstream.requests)
        async with fixture.maker() as db:
            assert bool(await store.load_signals(db, 1)) is (action == "unlink")


async def test_unlink_deletes_history_and_retained_controls_remain_when_unconfigured(
    tmp_path: Path,
) -> None:
    async with trakt_harness(tmp_path) as fixture:
        await fixture.seed()
        async with fixture.maker() as db:
            await store.record_signal(db, 1, "movie", 550, "watched_trakt")
            await db.commit()
        fixture.settings.seerr_internal_url = None
        summary = (await fixture.client.get("/api/v1/account")).json()
        assert next(p for p in summary["providers"] if p["provider"] == "trakt")["can_unlink"]
        assert (
            await fixture.client.post("/api/v1/account/links/trakt/unlink", json={})
        ).status_code == 204
        fixture.settings.trakt_client_id = None
        summary = (await fixture.client.get("/api/v1/account")).json()
        assert next(p for p in summary["providers"] if p["provider"] == "trakt")["linked"] is False
        assert summary["taste_sources"]["trakt"]
        assert (
            await fixture.client.post("/api/v1/account/taste-sources/trakt/clear")
        ).status_code == 204
        assert "trakt" not in [
            p["provider"] for p in (await fixture.client.get("/api/v1/account")).json()["providers"]
        ]

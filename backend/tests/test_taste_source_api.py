# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from tests.factories import user_with_links
from tests.test_account_api import db_call
from tests.test_recommend_seed import _taste
from tests.test_recommendations_api import _app, _client, _seed_session

from tasterr.auth.login import get_link
from tasterr.clients.seerr import SeerrClient, SeerrHistoricalRequest
from tasterr.db.models import LinkedAccount, Profile, User, utcnow
from tasterr.recommend import store
from tasterr.recommend.seed import seed_in_background
from tasterr.recommend.signals import SOURCE_KINDS, TasteSource


def test_toggle_changes_only_the_caller_and_retains_imported_signals(tmp_path: Path) -> None:
    path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(path)

    async def prepare(db: AsyncSession) -> None:
        other = await user_with_links(db, seerr_user_id=2, display_name="other", auth_type="local")
        await db.flush()
        for member in (user_id, other.id):
            await store.record_signal(db, member, "movie", 1, "seed_request_history")
            await store.save_profile(db, member, {"genre:drama": 1})

    db_call(path, prepare)
    with _client(_app(tmp_path), token) as client:
        assert all(client.get("/api/v1/account").json()["taste_sources"].values())
        assert (
            client.post(
                "/api/v1/account/taste-sources", json={"source": "seerr", "enabled": False}
            ).status_code
            == 204
        )

    async def verify(db: AsyncSession) -> None:
        assert await store.excluded_sources(db, user_id) == ["seerr"]
        assert await store.excluded_sources(db, 2) == []
        assert (
            len(await store.load_signals(db, user_id)) == len(await store.load_signals(db, 2)) == 1
        )
        assert await store.load_profile(db, user_id) is None
        assert await store.load_profile(db, 2) is not None

    db_call(path, verify)


@pytest.mark.parametrize("source", list(SOURCE_KINDS))
def test_clear_is_scoped_and_preserves_preferences_and_watermark(
    tmp_path: Path, source: TasteSource
) -> None:
    path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(path)
    stamp = utcnow()

    async def prepare(db: AsyncSession) -> None:
        other = await user_with_links(db, seerr_user_id=2, display_name="other", auth_type="local")
        await db.flush()
        for member in (user_id, other.id):
            for kind in (
                "seed_request_history",
                "watched_plex",
                "watched_jellyfin",
                "detail_open",
                "watchlist",
                "request",
                "not_interested",
            ):
                await store.record_signal(db, member, "movie", 10, kind)
            db.add(Profile(user_id=member, vector="{}"))
        await store.set_source_enabled(db, user_id, source, False)
        # Clearing must invalidate a profile independently of a preceding toggle.
        await store.save_profile(db, user_id, {"genre:drama": 1})
        for name in ("plex", "jellyfin"):
            db.add(
                LinkedAccount(
                    user_id=user_id, provider=name, external_id=name, display_name="Viewer"
                )
            )
        await db.flush()
        for link in await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user_id)):
            link.sync_attempted_at = link.sync_synced_at = stamp

    db_call(path, prepare)
    with _client(_app(tmp_path), token) as client:
        assert client.post(f"/api/v1/account/taste-sources/{source}/clear").status_code == 204
        response = client.get("/api/v1/account").json()
        assert response["taste_sources"] == {name: name != source for name in SOURCE_KINDS}

    async def verify(db: AsyncSession) -> None:
        remaining = await store.load_signals(db, user_id)
        assert len(remaining) == 6
        assert all(row.kind not in SOURCE_KINDS[source] for row in remaining)
        assert len(await store.load_signals(db, 2)) == 7
        assert await db.get(Profile, user_id) is None
        assert await db.get(Profile, 2) is not None
        other = await db.get(User, 2)
        assert other is not None and other.taste_excluded_sources == []
        for link in await db.scalars(select(LinkedAccount).where(LinkedAccount.user_id == user_id)):
            assert link.sync_attempted_at == link.sync_synced_at == stamp

    db_call(path, verify)


@pytest.mark.parametrize("source", ["plex", "jellyfin"])
def test_unconfigured_unlinked_history_keeps_controls_card(
    tmp_path: Path, source: TasteSource
) -> None:
    path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(path)

    async def prepare(db: AsyncSession) -> None:
        await store.record_signal(db, user_id, "movie", 1, next(iter(SOURCE_KINDS[source])))

    db_call(path, prepare)
    with _client(_app(tmp_path, seerr=False), token) as client:
        providers = client.get("/api/v1/account").json()["providers"]
        retained = next(row for row in providers if row["provider"] == source)
        assert retained == {
            "provider": source,
            "available": False,
            "linked": False,
            "display_name": None,
            "linked_at": None,
            "can_unlink": False,
        }
        assert client.post(f"/api/v1/account/taste-sources/{source}/clear").status_code == 204
        assert all(
            row["provider"] != source for row in client.get("/api/v1/account").json()["providers"]
        )


@pytest.mark.parametrize(
    "source", ["request", "watchlist", "not_interested", "seerr_requests", "unknown"]
)
def test_unknown_or_deliberate_source_is_rejected(tmp_path: Path, source: str) -> None:
    path = tmp_path / "tasterr.db"
    token, _user_id = _seed_session(path)
    with _client(_app(tmp_path), token) as client:
        assert (
            client.post(
                "/api/v1/account/taste-sources", json={"source": source, "enabled": False}
            ).status_code
            == 422
        )
        assert client.post(f"/api/v1/account/taste-sources/{source}/clear").status_code == 422
        assert all(client.get("/api/v1/account").json()["taste_sources"].values())


@pytest.mark.parametrize("previous_sync", [False, True])
def test_clear_reimport_obeys_overlap_or_never_synced_window(
    tmp_path: Path, previous_sync: bool
) -> None:
    path = tmp_path / "tasterr.db"
    token, user_id = _seed_session(path)
    stamp = utcnow() - timedelta(hours=7)
    old, recent = stamp - timedelta(days=2), stamp - timedelta(hours=1)

    async def prepare(db: AsyncSession) -> None:
        link = await get_link(db, user_id, "seerr")
        assert link is not None
        link.sync_attempted_at = stamp
        link.sync_synced_at = stamp if previous_sync else None
        await store.record_signal(db, user_id, "movie", 1, "seed_request_history", old)
        await store.record_signal(db, user_id, "movie", 2, "seed_request_history", recent)

    db_call(path, prepare)

    class History:
        async def list_requests(self, _user_id: int) -> list[SeerrHistoricalRequest]:
            return [
                SeerrHistoricalRequest("movie", 1, old),
                SeerrHistoricalRequest("movie", 2, recent),
            ]

    app = _app(tmp_path)
    with _client(app, token) as client:
        assert client.post("/api/v1/account/taste-sources/seerr/clear").status_code == 204

        async def sync() -> None:
            await seed_in_background(
                app.state.sessionmaker,
                _taste,
                cast(SeerrClient, History()),
                app.state.seeding,
                user_id,
            )

        assert client.portal is not None
        client.portal.call(sync)

    async def verify(db: AsyncSession) -> None:
        assert {row.tmdb_id for row in await store.load_signals(db, user_id)} == (
            {2} if previous_sync else {1, 2}
        )

    db_call(path, verify)

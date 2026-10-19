# pyright: reportPrivateUsage=false
# pyright: reportUnknownMemberType=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession
from tests.factories import user_with_links
from tests.test_recommendations_api import _app, _client, _run_db, _seed_session

from tasterr.recommend import store
from tasterr.recommend.signals import SOURCE_KINDS, TasteSource


@pytest.mark.parametrize("source", list(SOURCE_KINDS))
def test_household_and_onboarding_ignore_disabled_sources(
    tmp_path: Path, source: TasteSource
) -> None:
    app = _app(tmp_path)
    token, user_id = _seed_session(tmp_path / "tasterr.db")

    async def prepare(db: AsyncSession) -> None:
        other = await user_with_links(db, seerr_user_id=2, display_name="other", auth_type="local")
        await db.flush()
        await store.record_signal(db, other.id, "movie", 2, "watchlist")
        await store.record_signal(db, user_id, "movie", 1, next(iter(SOURCE_KINDS[source])))
        await store.set_source_enabled(db, user_id, source, False)

    _run_db(tmp_path / "tasterr.db", prepare)
    with _client(app, token) as client:
        members = client.get("/api/v1/recommendations/household-members").json()
        assert [m["has_taste_signals"] for m in members] == [False, True]
        assert set(members[0]) == {"id", "display_name", "avatar_url", "has_taste_signals"}
        assert (
            client.post(
                "/api/v1/recommendations/household-blend", json={"user_ids": [1, 2]}
            ).status_code
            == 400
        )
        assert client.get("/api/v1/taste-onboarding").json() == {"state": "show"}

        async def enable(db: AsyncSession) -> None:
            await store.set_source_enabled(db, user_id, source, True)

        _run_db(tmp_path / "tasterr.db", enable)
        assert client.get("/api/v1/taste-onboarding").json() == {"state": "done"}
        assert client.get("/api/v1/recommendations/household-members").json()[0][
            "has_taste_signals"
        ]

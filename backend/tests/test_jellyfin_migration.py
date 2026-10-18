# pyright: reportPrivateUsage=false
from pathlib import Path

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_db_migrations import _downgrade, _upgrade

from tasterr.db.engine import create_engine
from tasterr.db.models import LinkedAccount, Profile, Signal, User, UserSession, utcnow
from tasterr.recommend.store import record_signal


async def test_upgrade_upserts_all_unique_kinds_and_downgrade_has_no_orphans(
    tmp_path: Path,
) -> None:
    engine = create_engine(tmp_path / "migration.db")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade, "0007")
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            await connection.commit()
            await connection.run_sync(_upgrade, "0008")
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            for user_id in (1, 2, 3):
                db.add(User(id=user_id, display_name="Viewer"))
                await db.flush()
                db.add_all(
                    [
                        LinkedAccount(
                            user_id=user_id,
                            provider="jellyfin" if user_id != 3 else "seerr",
                            external_id=str(user_id),
                            display_name="Viewer",
                        ),
                        UserSession(user_id=user_id, token_hash=str(user_id), expires_at=utcnow()),
                    ]
                )
                for kind in (
                    "watchlist",
                    "not_interested",
                    "seed_request_history",
                    "watched_plex",
                    "watched_jellyfin",
                ):
                    assert await record_signal(db, user_id, "movie", 550, kind)
                    assert not await record_signal(
                        db, user_id, "movie", 550, kind, utcnow().replace(year=2025)
                    )
                db.add(Profile(user_id=user_id, vector="{}"))
            db.add(
                LinkedAccount(user_id=2, provider="seerr", external_id="2", display_name="Viewer")
            )
            await db.commit()
        async with engine.connect() as connection:
            await connection.run_sync(_downgrade, "0007")
            assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
        async with maker() as db:
            assert list(await db.scalars(select(User.id).order_by(User.id))) == [2, 3]
            assert (await db.scalars(select(Profile))).all() == []
            for model in (LinkedAccount, UserSession, Signal):
                assert {row.user_id for row in (await db.scalars(select(model))).all()} == {2, 3}
            assert set(await db.scalars(select(LinkedAccount.provider))) == {"seerr"}
            assert "watched_jellyfin" not in set(await db.scalars(select(Signal.kind)))
    finally:
        await engine.dispose()

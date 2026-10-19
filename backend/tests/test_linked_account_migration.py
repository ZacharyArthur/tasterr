# pyright: reportPrivateUsage=false
from pathlib import Path

import pytest
from sqlalchemy import delete, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker
from tests.test_db_migrations import _downgrade, _upgrade

from tasterr.db.engine import create_engine
from tasterr.db.migrate import upgrade_to_head
from tasterr.db.models import LinkedAccount, Profile, Signal, User, UserSession, utcnow


async def test_upgrade_and_downgrade_preserve_children(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "migration.db")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade, "0006")
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            await connection.execute(
                text(
                    "INSERT INTO users (id, seerr_user_id, display_name, avatar_url, auth_type, "
                    "is_admin, taste_onboarding_seen, created_at, last_login_at) VALUES "
                    "(1, 8, 'member', 'avatar', 'plex', 1, 1, '2026-01-01', '2026-01-02')"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO signals (user_id, tmdb_id, media_type, kind, weight, created_at) "
                    "VALUES (1, 10, 'movie', 'watchlist', 2, CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO profiles (user_id, vector, computed_at) VALUES (1, "
                    "'{}', CURRENT_TIMESTAMP)"
                )
            )
            await connection.execute(
                text(
                    "INSERT INTO sessions (user_id, token_hash, seerr_cookie, plex_token_enc, "
                    "created_at, expires_at, last_seen_at) VALUES (1, 'hash', 'secret-cookie', "
                    "'secret-token', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                )
            )
            await connection.commit()
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            link = (await db.scalars(select(LinkedAccount))).one()
            assert (link.provider, link.external_id, link.display_name, link.avatar_url) == (
                "seerr",
                "8",
                "member",
                "avatar",
            )
            assert str(link.linked_at) == "2026-01-01 00:00:00"
            assert link.credential_enc is link.sync_attempted_at is link.sync_synced_at is None
            assert (await db.scalars(select(UserSession))).all() == []
            assert (await db.get(User, 1)).taste_onboarding_seen  # type: ignore[union-attr]
            orphan = User(display_name="no-seerr")
            db.add(orphan)
            await db.flush()
            db.add_all(
                [
                    Signal(
                        user_id=orphan.id, tmdb_id=20, media_type="tv", kind="request", weight=3
                    ),
                    Profile(user_id=orphan.id, vector="{}"),
                    LinkedAccount(
                        user_id=orphan.id, provider="plex", external_id="2", display_name="p"
                    ),
                    UserSession(user_id=orphan.id, token_hash="orphan", expires_at=utcnow()),
                ]
            )
            db.add(LinkedAccount(user_id=1, provider="plex", external_id="1", display_name="p"))
            await db.commit()
        async with engine.connect() as connection:
            await connection.run_sync(_downgrade, "0006")
            assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            assert (
                await connection.execute(text("SELECT seerr_user_id, auth_type FROM users"))
            ).all() == [(8, "plex")]
            for table in ("signals", "profiles"):
                assert (await connection.execute(text(f"SELECT user_id FROM {table}"))).all() == [
                    (1,)
                ]
            assert (
                await connection.execute(text("SELECT count(*) FROM sessions"))
            ).scalar_one() == 0
        await upgrade_to_head(engine)
        async with maker() as db:
            assert len((await db.scalars(select(Signal))).all()) == 1
            assert await db.get(Profile, 1) is not None
    finally:
        await engine.dispose()


async def test_link_constraints_and_user_id_not_reused(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "unique.db")
    try:
        await upgrade_to_head(engine)
        maker = async_sessionmaker(engine, expire_on_commit=False)
        async with maker() as db:
            user = User(display_name="first")
            db.add(user)
            await db.flush()
            first_id = user.id
            db.add(
                LinkedAccount(user_id=user.id, provider="seerr", external_id="1", display_name="s")
            )
            await db.commit()
            for user_id, external_id in ((user.id, "2"), (user.id + 1, "1")):
                if user_id != user.id:
                    db.add(User(id=user_id, display_name="second"))
                    await db.commit()
                db.add(
                    LinkedAccount(
                        user_id=user_id, provider="seerr", external_id=external_id, display_name="s"
                    )
                )
                with pytest.raises(IntegrityError):
                    await db.commit()
                await db.rollback()
                await db.refresh(user)
            await db.execute(delete(User))
            await db.commit()
            new_user = User(display_name="new")
            db.add(new_user)
            await db.commit()
            assert new_user.id > first_id + 1
    finally:
        await engine.dispose()


async def test_failed_upgrade_rolls_back_ddl_and_can_be_retried(tmp_path: Path) -> None:
    engine = create_engine(tmp_path / "failed-upgrade.db")
    try:
        async with engine.connect() as connection:
            await connection.run_sync(_upgrade, "0006")
            await connection.execute(text("PRAGMA foreign_keys=OFF"))
            await connection.execute(
                text(
                    "INSERT INTO signals (user_id, tmdb_id, media_type, kind, weight, created_at) "
                    "VALUES (999, 10, 'movie', 'watchlist', 2, CURRENT_TIMESTAMP)"
                )
            )
            await connection.commit()
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.commit()
            with pytest.raises(RuntimeError, match="foreign-key violations"):
                await connection.run_sync(_upgrade, "head")
            assert (await connection.execute(text("PRAGMA foreign_keys"))).scalar_one() == 1
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == "0006"
            assert (
                await connection.execute(
                    text("SELECT name FROM sqlite_master WHERE name = 'linked_accounts'")
                )
            ).all() == []
            await connection.execute(text("DELETE FROM signals WHERE user_id = 999"))
            await connection.commit()
        await upgrade_to_head(engine)
        async with engine.connect() as connection:
            assert (
                await connection.execute(text("SELECT version_num FROM alembic_version"))
            ).scalar_one() == "0009"
            assert (await connection.execute(text("PRAGMA foreign_key_check"))).all() == []
    finally:
        await engine.dispose()

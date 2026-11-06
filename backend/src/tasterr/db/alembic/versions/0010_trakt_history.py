"""Include Trakt watch facts and rebuild profiles under watch deduplication.

Revision ID: 0010
Revises: 0009
"""

import json
from collections.abc import Sequence
from typing import cast

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD = (
    "kind IN ('watchlist', 'not_interested', 'seed_request_history', "
    "'watched_plex', 'watched_jellyfin')"
)
_NEW = (
    "kind IN ('watchlist', 'not_interested', 'seed_request_history', "
    "'watched_plex', 'watched_jellyfin', 'watched_trakt')"
)


def upgrade() -> None:
    _replace_index(_NEW)
    op.execute(sa.text("DELETE FROM profiles"))


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM profiles WHERE user_id IN "
            "(SELECT user_id FROM signals WHERE kind = 'watched_trakt') "
            "OR user_id IN (SELECT user_id FROM linked_accounts WHERE provider = 'trakt')"
        )
    )
    users = sa.table(
        "users", sa.column("id", sa.Integer), sa.column("taste_excluded_sources", sa.Text)
    )
    profiles = sa.table("profiles", sa.column("user_id", sa.Integer))
    for user_id, encoded in connection.execute(
        sa.select(users.c.id, users.c.taste_excluded_sources)
    ):
        sources: object = json.loads(encoded)
        if isinstance(sources, list) and "trakt" in sources:
            connection.execute(
                users.update()
                .where(users.c.id == user_id)
                .values(
                    taste_excluded_sources=json.dumps(
                        [source for source in cast("list[object]", sources) if source != "trakt"]
                    )
                )
            )
            connection.execute(profiles.delete().where(profiles.c.user_id == user_id))
    connection.execute(sa.text("DELETE FROM signals WHERE kind = 'watched_trakt'"))
    connection.execute(sa.text("DELETE FROM linked_accounts WHERE provider = 'trakt'"))
    _replace_index(_OLD)


def _replace_index(predicate: str) -> None:
    op.drop_index("ux_signals_unique_per_title", table_name="signals")
    op.create_index(
        "ux_signals_unique_per_title",
        "signals",
        ["user_id", "media_type", "tmdb_id", "kind"],
        unique=True,
        sqlite_where=sa.text(predicate),
    )

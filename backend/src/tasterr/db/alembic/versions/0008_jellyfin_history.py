"""Include Jellyfin's canonical watch facts in the unique index.

Revision ID: 0008
Revises: 0007
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_OLD_KINDS = "('watchlist', 'not_interested', 'seed_request_history', 'watched_plex')"
_NEW_KINDS = (
    "('watchlist', 'not_interested', 'seed_request_history', 'watched_plex', 'watched_jellyfin')"
)


def upgrade() -> None:
    _replace_index(_NEW_KINDS)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM profiles WHERE user_id IN "
            "(SELECT user_id FROM signals WHERE kind = 'watched_jellyfin')"
        )
    )
    connection.execute(sa.text("DELETE FROM signals WHERE kind = 'watched_jellyfin'"))
    connection.execute(sa.text("DELETE FROM linked_accounts WHERE provider = 'jellyfin'"))
    for table in ("signals", "profiles", "sessions"):
        connection.execute(
            sa.text(
                f"DELETE FROM {table} WHERE user_id IN (SELECT id FROM users WHERE NOT EXISTS "
                "(SELECT 1 FROM linked_accounts WHERE user_id = users.id))"
            )
        )
    connection.execute(
        sa.text(
            "DELETE FROM users WHERE NOT EXISTS "
            "(SELECT 1 FROM linked_accounts WHERE user_id = users.id)"
        )
    )
    _replace_index(_OLD_KINDS)


def _replace_index(kinds: str) -> None:
    op.drop_index("ux_signals_unique_per_title", table_name="signals")
    op.create_index(
        "ux_signals_unique_per_title",
        "signals",
        ["user_id", "media_type", "tmdb_id", "kind"],
        unique=True,
        sqlite_where=sa.text(f"kind IN {kinds}"),
    )

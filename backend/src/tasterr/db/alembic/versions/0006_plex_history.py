"""Track bounded Plex history imports.

Revision ID: 0006
Revises: 0005
Create Date: 2026-08-25

"""

import json
from collections.abc import Sequence
from typing import cast

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_V2_RAIL_TYPES = {"continue-watching", "unexpected-picks", "household-blend"}
_OLD_UNIQUE_KINDS = "('watchlist', 'not_interested', 'seed_request_history')"
_NEW_UNIQUE_KINDS = "('watchlist', 'not_interested', 'seed_request_history', 'watched_plex')"


def upgrade() -> None:
    op.add_column("users", sa.Column("plex_history_attempted_at", sa.DateTime(), nullable=True))
    op.add_column("users", sa.Column("plex_history_synced_at", sa.DateTime(), nullable=True))
    _replace_signal_index(_NEW_UNIQUE_KINDS)


def downgrade() -> None:
    connection = op.get_bind()
    connection.execute(
        sa.text(
            "DELETE FROM profiles WHERE user_id IN "
            "(SELECT user_id FROM signals WHERE kind = 'watched_plex')"
        )
    )
    connection.execute(sa.text("DELETE FROM signals WHERE kind = 'watched_plex'"))
    _replace_signal_index(_OLD_UNIQUE_KINDS)
    op.drop_column("users", "plex_history_synced_at")
    op.drop_column("users", "plex_history_attempted_at")
    _strip_v2_rail_types()


def _replace_signal_index(kinds: str) -> None:
    op.drop_index("ux_signals_unique_per_title", table_name="signals")
    op.create_index(
        "ux_signals_unique_per_title",
        "signals",
        ["user_id", "media_type", "tmdb_id", "kind"],
        unique=True,
        sqlite_where=sa.text(f"kind IN {kinds}"),
    )


def _strip_v2_rail_types() -> None:
    connection = op.get_bind()
    rows = connection.execute(sa.text("SELECT key, value FROM settings")).all()
    for key, raw_value in rows:
        try:
            parsed = json.loads(cast("str", raw_value))
        except (TypeError, ValueError):
            continue
        if not isinstance(parsed, dict):
            continue
        value = cast("dict[str, object]", parsed)
        disabled = value.get("disabled_rail_types")
        if not isinstance(disabled, list):
            continue
        disabled_items = cast("list[object]", disabled)
        filtered = [
            item
            for item in disabled_items
            if not isinstance(item, str) or item not in _V2_RAIL_TYPES
        ]
        if filtered == disabled:
            continue
        value["disabled_rail_types"] = filtered
        connection.execute(
            sa.text("UPDATE settings SET value = :value WHERE key = :key"),
            {"key": key, "value": json.dumps(value, separators=(",", ":"))},
        )

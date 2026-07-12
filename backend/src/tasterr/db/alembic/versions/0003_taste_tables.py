"""Taste tables for M4 (SPEC §5): signals, title_features, profiles.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("tmdb_id", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=8), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("weight", sa.Float(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_signals_user_id_kind", "signals", ["user_id", "kind"])
    # DB-enforced at-most-one-row-per-title for the toggle and seed kinds:
    # application-level exists-checks race across concurrent sessions (a
    # background login-seed vs. an inline reset); the index cannot.
    op.create_index(
        "ux_signals_unique_per_title",
        "signals",
        ["user_id", "media_type", "tmdb_id", "kind"],
        unique=True,
        sqlite_where=sa.text("kind IN ('watchlist', 'not_interested', 'seed_request_history')"),
    )
    op.create_table(
        "title_features",
        sa.Column("tmdb_id", sa.Integer(), primary_key=True),
        sa.Column("media_type", sa.String(length=8), primary_key=True),
        sa.Column("features", sa.String(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
    )
    op.create_table(
        "profiles",
        sa.Column(
            "user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("vector", sa.String(), nullable=False),
        sa.Column("computed_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    # Drops real user behavior (design.md Risks) — acceptable pre-1.0; the
    # seed rebuilds the request-history baseline at next login.
    op.drop_table("profiles")
    op.drop_table("title_features")
    op.drop_table("signals")

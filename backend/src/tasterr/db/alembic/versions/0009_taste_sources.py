"""Store each user's excluded taste sources.

Revision ID: 0009
Revises: 0008
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("taste_excluded_sources", sa.Text(), nullable=False, server_default="[]")
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM profiles WHERE user_id IN "
            "(SELECT id FROM users WHERE taste_excluded_sources != '[]')"
        )
    )
    op.drop_column("users", "taste_excluded_sources")

"""Baseline: proves the migration pipeline end to end; no tables yet.

Revision ID: 0001
Revises:
Create Date: 2026-07-03

"""

from collections.abc import Sequence

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass

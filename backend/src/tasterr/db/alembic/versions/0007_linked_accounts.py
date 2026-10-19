"""Move external identities and credentials to linked accounts.

Revision ID: 0007
Revises: 0006
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "linked_accounts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("provider", sa.String(16), nullable=False),
        sa.Column("external_id", sa.String(64), nullable=False),
        sa.Column("display_name", sa.String(), nullable=False),
        sa.Column("avatar_url", sa.String(), nullable=True),
        sa.Column("credential_enc", sa.String(), nullable=True),
        sa.Column("sync_attempted_at", sa.DateTime(), nullable=True),
        sa.Column("sync_synced_at", sa.DateTime(), nullable=True),
        sa.Column("linked_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("provider", "external_id", name="uq_linked_accounts_external"),
        sa.UniqueConstraint("user_id", "provider", name="uq_linked_accounts_user_provider"),
    )
    op.create_index("ix_linked_accounts_user_id", "linked_accounts", ["user_id"])
    op.execute(
        sa.text(
            "INSERT INTO linked_accounts (user_id, provider, external_id, display_name, "
            "avatar_url, linked_at) "
            "SELECT id, 'seerr', CAST(seerr_user_id AS TEXT), display_name, avatar_url, "
            "created_at FROM users"
        )
    )
    op.execute(sa.text("DELETE FROM sessions"))
    with op.batch_alter_table("sessions") as batch:
        batch.drop_column("seerr_cookie")
        batch.drop_column("plex_token_enc")
    with op.batch_alter_table("users", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.drop_constraint("uq_users_seerr_user_id", type_="unique")
        batch.drop_column("seerr_user_id")
        batch.drop_column("auth_type")
        batch.drop_column("plex_history_attempted_at")
        batch.drop_column("plex_history_synced_at")
        batch.add_column(sa.Column("seerr_unlinked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM sessions"))
    for table in ("signals", "profiles", "linked_accounts"):
        op.execute(
            sa.text(
                f"DELETE FROM {table} WHERE user_id IN (SELECT id FROM users WHERE id NOT IN "
                "(SELECT user_id FROM linked_accounts WHERE provider = 'seerr'))"
            )
        )
    op.execute(
        sa.text(
            "DELETE FROM users WHERE id NOT IN (SELECT user_id FROM linked_accounts "
            "WHERE provider = 'seerr')"
        )
    )
    with op.batch_alter_table("users", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.add_column(sa.Column("seerr_user_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("auth_type", sa.String(8), nullable=True))
        batch.add_column(sa.Column("plex_history_attempted_at", sa.DateTime(), nullable=True))
        batch.add_column(sa.Column("plex_history_synced_at", sa.DateTime(), nullable=True))
        batch.drop_column("seerr_unlinked_at")
    op.execute(
        sa.text(
            "UPDATE users SET seerr_user_id = (SELECT CAST(external_id AS INTEGER) FROM "
            "linked_accounts "
            "WHERE user_id = users.id AND provider = 'seerr'), auth_type = CASE WHEN EXISTS "
            "(SELECT 1 FROM linked_accounts WHERE user_id = users.id AND provider = 'plex') "
            "THEN 'plex' ELSE 'local' END"
        )
    )
    with op.batch_alter_table("users", table_kwargs={"sqlite_autoincrement": True}) as batch:
        batch.alter_column("seerr_user_id", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("auth_type", existing_type=sa.String(8), nullable=False)
        batch.create_unique_constraint("uq_users_seerr_user_id", ["seerr_user_id"])
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("seerr_cookie", sa.String(), nullable=False))
        batch.add_column(sa.Column("plex_token_enc", sa.String(), nullable=True))
    op.drop_table("linked_accounts")

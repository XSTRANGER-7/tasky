"""users: supabase_auth_id (copied into Supabase Auth) and onboarded_at (first sign-in page)

Revision ID: 0010
Revises: 0009
Create Date: 2026-09-24 22:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("supabase_auth_id", sa.Uuid(), nullable=True))
    op.create_unique_constraint("uq_users_supabase_auth_id", "users", ["supabase_auth_id"])
    op.add_column("users", sa.Column("onboarded_at", sa.DateTime(timezone=True), nullable=True))
    # Accounts that already exist are past their first sign-in.
    op.execute("UPDATE users SET onboarded_at = created_at")


def downgrade() -> None:
    op.drop_column("users", "onboarded_at")
    op.drop_constraint("uq_users_supabase_auth_id", "users", type_="unique")
    op.drop_column("users", "supabase_auth_id")

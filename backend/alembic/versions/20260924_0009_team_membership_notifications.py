"""membership emails: added to a team, role changed, removed

Revision ID: 0009
Revises: 0008
Create Date: 2026-09-24 20:00:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_KINDS = ("team_member_added", "team_role_changed", "team_member_removed")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_KINDS:
            op.execute(f"ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop enum values: remove the rows that use them so older code copes.
    kinds = ", ".join(f"'{k}'" for k in NEW_KINDS)
    op.execute(f"DELETE FROM in_app_notifications WHERE kind::text IN ({kinds})")
    op.execute(f"DELETE FROM notification_outbox WHERE kind::text IN ({kinds})")

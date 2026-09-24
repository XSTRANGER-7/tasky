"""notification kinds: incident updated, added to an incident

Revision ID: 0012
Revises: 0011
Create Date: 2026-09-24 23:30:00+00:00
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_KINDS = ("incident_updated", "incident_added")


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_KINDS:
            op.execute(f"ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # Postgres cannot drop enum values: remove the rows that use them so older code copes.
    kinds = ", ".join(f"'{k}'" for k in NEW_KINDS)
    op.execute(f"DELETE FROM in_app_notifications WHERE kind::text IN ({kinds})")
    op.execute(f"DELETE FROM notification_outbox WHERE kind::text IN ({kinds})")

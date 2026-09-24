"""incident_assignees: several people can be assigned to one task

Revision ID: 0013
Revises: 0012
Create Date: 2026-09-25 10:00:00+00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "incident_assignees",
        sa.Column("incident_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("position", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["incident_id"],
            ["incidents.id"],
            name=op.f("fk_incident_assignees_incident_id_incidents"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_incident_assignees_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("incident_id", "user_id", name=op.f("pk_incident_assignees")),
    )
    op.create_index("ix_incident_assignees_user", "incident_assignees", ["user_id"])
    # Today's single assignee becomes the lead (and only) assignee.
    op.execute(
        "INSERT INTO incident_assignees (incident_id, user_id, position) "
        "SELECT id, assignee_id, 0 FROM incidents WHERE assignee_id IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_index("ix_incident_assignees_user", table_name="incident_assignees")
    op.drop_table("incident_assignees")

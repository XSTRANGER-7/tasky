"""team admins replace platform admins

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-24 18:00:00+00:00

There is no platform-wide admin any more: whoever creates a team is its admin.

* Team roles become admin / member / viewer (former owners become admins).
* ``users.role`` is dropped: what someone may do comes only from their team memberships.
* The email outbox and AI suggestions record their team, so each team's admins see only
  their own team's email and AI usage.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _swap_team_role(values: tuple[str, ...], mapping: str) -> None:
    """Recreate the team_role enum with ``values`` (Postgres cannot drop enum values)."""
    op.execute("ALTER TYPE team_role RENAME TO team_role_old")
    op.execute(f"CREATE TYPE team_role AS ENUM ({', '.join(repr(v) for v in values)})")
    op.execute("ALTER TABLE team_memberships ALTER COLUMN role DROP DEFAULT")
    op.execute(
        "ALTER TABLE team_memberships ALTER COLUMN role TYPE team_role "
        f"USING ({mapping.format(col='role')})::team_role"
    )
    op.execute("ALTER TABLE team_memberships ALTER COLUMN role SET DEFAULT 'member'")
    op.execute(
        "ALTER TABLE team_join_requests ALTER COLUMN granted_role TYPE team_role "
        f"USING ({mapping.format(col='granted_role')})::team_role"
    )
    op.execute("DROP TYPE team_role_old")


def upgrade() -> None:
    _swap_team_role(
        ("admin", "member", "viewer"),
        "CASE {col}::text WHEN 'owner' THEN 'admin' ELSE {col}::text END",
    )

    op.drop_column("users", "role")
    op.execute("DROP TYPE IF EXISTS user_role")

    op.add_column("notification_outbox", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notification_outbox_team_id_teams",
        "notification_outbox",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_notification_outbox_team_created", "notification_outbox", ["team_id", "created_at"]
    )
    op.execute(
        "UPDATE notification_outbox o SET team_id = i.team_id "
        "FROM incidents i WHERE i.id = o.incident_id"
    )

    op.add_column("ai_suggestions", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_ai_suggestions_team_id_teams",
        "ai_suggestions",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index("ix_ai_suggestions_team_id", "ai_suggestions", ["team_id"])
    op.execute(
        "UPDATE ai_suggestions s SET team_id = i.team_id FROM incidents i WHERE i.id = s.incident_id"
    )
    # Suggestions made before an incident existed: the asker's team, when they have one.
    op.execute(
        "UPDATE ai_suggestions s SET team_id = m.team_id FROM ("
        "  SELECT user_id, min(team_id::text)::uuid AS team_id FROM team_memberships"
        "  GROUP BY user_id HAVING count(*) = 1"
        ") m WHERE s.team_id IS NULL AND m.user_id = s.user_id"
    )


def downgrade() -> None:
    op.drop_index("ix_ai_suggestions_team_id", table_name="ai_suggestions")
    op.drop_constraint("fk_ai_suggestions_team_id_teams", "ai_suggestions")
    op.drop_column("ai_suggestions", "team_id")
    op.drop_index("ix_notification_outbox_team_created", table_name="notification_outbox")
    op.drop_constraint("fk_notification_outbox_team_id_teams", "notification_outbox")
    op.drop_column("notification_outbox", "team_id")

    user_role = postgresql.ENUM("admin", "member", "viewer", name="user_role")
    user_role.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "users",
        sa.Column("role", user_role, server_default="member", nullable=False),
    )
    # Team admins get back the old platform admin role; everyone else is a member.
    op.execute(
        "UPDATE users SET role = 'admin' WHERE id IN "
        "(SELECT user_id FROM team_memberships WHERE role = 'admin')"
    )

    _swap_team_role(("owner", "admin", "member", "viewer"), "{col}::text")

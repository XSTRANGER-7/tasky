"""teams, join requests, google sign-in, password reset

Revision ID: 0007
Revises: 0006
Create Date: 2026-09-24 10:00:00+00:00

Existing incidents are moved into a "General" team that every existing user joins with
the equivalent role, so an upgraded install keeps working exactly as before.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

NEW_KINDS = ("team_join_requested", "team_join_approved", "team_join_rejected", "password_reset")

team_role = postgresql.ENUM(
    "owner", "admin", "member", "viewer", name="team_role", create_type=False
)
join_status = postgresql.ENUM(
    "pending", "approved", "rejected", "cancelled", name="join_request_status", create_type=False
)

BACKFILL = """
DO $$
DECLARE general uuid;
BEGIN
  IF EXISTS (SELECT 1 FROM incidents) OR EXISTS (SELECT 1 FROM users) THEN
    general := gen_random_uuid();
    INSERT INTO teams (id, name, slug, description, created_by_id)
    VALUES (general, 'General', 'general', 'Everyone who was here before teams existed.',
            (SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1));
    INSERT INTO team_memberships (team_id, user_id, role)
    SELECT general, u.id,
           (CASE u.role WHEN 'admin' THEN 'admin' WHEN 'viewer' THEN 'viewer'
                        ELSE 'member' END)::team_role
    FROM users u;
    UPDATE team_memberships SET role = 'owner'
    WHERE team_id = general AND user_id = (
      SELECT id FROM users WHERE role = 'admin' ORDER BY created_at LIMIT 1);
    UPDATE incidents SET team_id = general;
  END IF;
END $$;
"""


def _timestamps() -> list[sa.Column[object]]:
    return [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
    ]


def upgrade() -> None:
    with op.get_context().autocommit_block():
        for value in NEW_KINDS:
            op.execute(f"ALTER TYPE notification_kind ADD VALUE IF NOT EXISTS '{value}'")

    team_role.create(op.get_bind(), checkfirst=True)
    join_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "teams",
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("slug", postgresql.CITEXT(), nullable=False),
        sa.Column("description", sa.String(500), server_default="", nullable=False),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"],
            ["users.id"],
            name="fk_teams_created_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
        sa.UniqueConstraint("slug", name="uq_teams_slug"),
    )
    op.create_table(
        "team_memberships",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("role", team_role, server_default="member", nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_team_memberships_team_id_teams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_team_memberships_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("team_id", "user_id", name="pk_team_memberships"),
    )
    op.create_index("ix_team_memberships_user_id", "team_memberships", ["user_id"])

    op.create_table(
        "team_join_requests",
        sa.Column("team_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("message", sa.String(500), server_default="", nullable=False),
        sa.Column("status", join_status, server_default="pending", nullable=False),
        sa.Column("granted_role", team_role, nullable=True),
        sa.Column("decided_by_id", sa.Uuid(), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["team_id"],
            ["teams.id"],
            name="fk_team_join_requests_team_id_teams",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_team_join_requests_user_id_users",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["decided_by_id"],
            ["users.id"],
            name="fk_team_join_requests_decided_by_id_users",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_team_join_requests"),
    )
    op.create_index(
        "uq_team_join_requests_pending",
        "team_join_requests",
        ["team_id", "user_id"],
        unique=True,
        postgresql_where=sa.text("status = 'pending'"),
    )
    op.create_index(
        "ix_team_join_requests_team_status", "team_join_requests", ["team_id", "status"]
    )
    op.create_index("ix_team_join_requests_user_id", "team_join_requests", ["user_id"])

    op.create_table(
        "password_reset_tokens",
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_password_reset_tokens_user_id_users",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_password_reset_tokens"),
        sa.UniqueConstraint("token_hash", name="uq_password_reset_tokens_token_hash"),
    )
    op.create_index("ix_password_reset_tokens_user_id", "password_reset_tokens", ["user_id"])

    # ---- users: Google sign-in; a password is optional for Google-only accounts
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=True)
    op.add_column("users", sa.Column("google_sub", sa.String(255), nullable=True))
    op.create_unique_constraint("uq_users_google_sub", "users", ["google_sub"])

    # ---- incidents: owned by a team. Existing rows move into "General".
    op.add_column("incidents", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.execute(BACKFILL)
    op.alter_column("incidents", "team_id", existing_type=sa.Uuid(), nullable=False)
    op.create_foreign_key(
        "fk_incidents_team_id_teams", "incidents", "teams", ["team_id"], ["id"], ondelete="CASCADE"
    )
    op.create_index(
        "ix_incidents_team_created",
        "incidents",
        ["team_id", sa.text("created_at DESC")],
        postgresql_where=sa.text("NOT is_deleted"),
    )

    # ---- notifications that are not about an incident
    for table in ("notification_outbox", "in_app_notifications"):
        op.alter_column(table, "event_id", existing_type=sa.Uuid(), nullable=True)
        op.alter_column(table, "incident_id", existing_type=sa.Uuid(), nullable=True)
    op.add_column("in_app_notifications", sa.Column("team_id", sa.Uuid(), nullable=True))
    op.add_column("in_app_notifications", sa.Column("link", sa.String(300), nullable=True))
    op.create_foreign_key(
        "fk_in_app_notifications_team_id_teams",
        "in_app_notifications",
        "teams",
        ["team_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.execute("DELETE FROM in_app_notifications WHERE incident_id IS NULL")
    op.execute("DELETE FROM notification_outbox WHERE incident_id IS NULL")
    op.drop_constraint("fk_in_app_notifications_team_id_teams", "in_app_notifications")
    op.drop_column("in_app_notifications", "link")
    op.drop_column("in_app_notifications", "team_id")
    for table in ("notification_outbox", "in_app_notifications"):
        op.alter_column(table, "incident_id", existing_type=sa.Uuid(), nullable=False)
        op.alter_column(table, "event_id", existing_type=sa.Uuid(), nullable=False)

    op.drop_index("ix_incidents_team_created", table_name="incidents")
    op.drop_constraint("fk_incidents_team_id_teams", "incidents")
    op.drop_column("incidents", "team_id")

    op.drop_constraint("uq_users_google_sub", "users")
    op.drop_column("users", "google_sub")
    # Google-only accounts get an unusable hash: they must reset their password.
    op.execute("UPDATE users SET password_hash = '!' WHERE password_hash IS NULL")
    op.alter_column("users", "password_hash", existing_type=sa.String(255), nullable=False)

    op.drop_index("ix_password_reset_tokens_user_id", table_name="password_reset_tokens")
    op.drop_table("password_reset_tokens")
    op.drop_index("ix_team_join_requests_user_id", table_name="team_join_requests")
    op.drop_index("ix_team_join_requests_team_status", table_name="team_join_requests")
    op.drop_index("uq_team_join_requests_pending", table_name="team_join_requests")
    op.drop_table("team_join_requests")
    op.drop_index("ix_team_memberships_user_id", table_name="team_memberships")
    op.drop_table("team_memberships")
    op.drop_table("teams")
    join_status.drop(op.get_bind(), checkfirst=True)
    team_role.drop(op.get_bind(), checkfirst=True)
    # notification_kind values cannot be removed from a Postgres enum; they stay unused.

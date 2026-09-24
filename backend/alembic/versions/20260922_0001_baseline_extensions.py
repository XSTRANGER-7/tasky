"""baseline: enable citext and pg_trgm

Both extensions are needed by later phases (CITEXT emails in Phase 1, trigram title
search in Phase 3). Enabling them in the first revision proves on day one that every
target database -- local Postgres 16, the CI service container and Neon -- supports them.

Revision ID: 0001
Revises:
Create Date: 2026-09-22
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS citext")
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")


def downgrade() -> None:
    op.execute("DROP EXTENSION IF EXISTS pg_trgm")
    op.execute("DROP EXTENSION IF EXISTS citext")

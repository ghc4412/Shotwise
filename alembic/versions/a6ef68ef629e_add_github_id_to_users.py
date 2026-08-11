"""add github_id to users

Revision ID: a6ef68ef629e
Revises: 8b8a38ba7c17
Create Date: 2026-08-11 16:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6ef68ef629e"
down_revision: str | Sequence[str] | None = "8b8a38ba7c17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add GitHub OAuth user id column (unique, nullable for env admin)."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.add_column(sa.Column("github_id", sa.String(), nullable=True))
        batch_op.create_unique_constraint("uq_users_github_id", ["github_id"])


def downgrade() -> None:
    """Drop GitHub OAuth user id column."""
    with op.batch_alter_table("users", schema=None) as batch_op:
        batch_op.drop_constraint("uq_users_github_id", type_="unique")
        batch_op.drop_column("github_id")

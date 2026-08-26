"""add optimistic concurrency revision to Creative Boards

Revision ID: p2creative002
Revises: p2creative001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p2creative002"
down_revision: str | Sequence[str] | None = "p2creative001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "creative_boards",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )


def downgrade() -> None:
    op.drop_column("creative_boards", "revision")

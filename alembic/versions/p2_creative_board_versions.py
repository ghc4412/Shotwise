"""add immutable Creative Board versions

Revision ID: p2creative003
Revises: wf4_merge_heads
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p2creative003"
down_revision: str | Sequence[str] | None = "wf4_merge_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_board_versions",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "board_id",
            sa.String(36),
            sa.ForeignKey("creative_boards.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("version_name", sa.String(200), nullable=False),
        sa.Column("snapshot_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("board_id", "version_number", name="uq_creative_board_version_number"),
    )
    op.create_index("ix_creative_board_versions_board", "creative_board_versions", ["board_id"])


def downgrade() -> None:
    op.drop_index("ix_creative_board_versions_board", table_name="creative_board_versions")
    op.drop_table("creative_board_versions")

"""add semantic Creative Board tables

Revision ID: p2creative001
Revises: p1creation001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p2creative001"
down_revision: str | Sequence[str] | None = "p1creation001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creative_boards",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("viewport_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("display_settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_creative_boards_user_id", "creative_boards", ["user_id"])
    op.create_index("ix_creative_boards_project", "creative_boards", ["project_id"])
    op.create_table(
        "creative_board_items",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("creative_boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column("item_type", sa.String(32), nullable=False),
        sa.Column("resource_type", sa.String(32), nullable=False),
        sa.Column("resource_id", sa.String(256), nullable=False),
        sa.Column("position_x", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("position_y", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="280"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="180"),
        sa.Column("group_id", sa.String(36)),
        sa.Column("display_settings_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_creative_board_items_board", "creative_board_items", ["board_id"])
    op.create_table(
        "creative_board_edges",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("board_id", sa.String(36), sa.ForeignKey("creative_boards.id", ondelete="CASCADE"), nullable=False),
        sa.Column(
            "source_item_id",
            sa.String(36),
            sa.ForeignKey("creative_board_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_item_id",
            sa.String(36),
            sa.ForeignKey("creative_board_items.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relation", sa.String(32), nullable=False),
        sa.Column("ordinal", sa.Integer()),
        sa.Column("metadata_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("board_id", "source_item_id", "target_item_id", "relation", name="uq_creative_board_edge"),
    )
    op.create_index("ix_creative_board_edges_board", "creative_board_edges", ["board_id"])


def downgrade() -> None:
    op.drop_index("ix_creative_board_edges_board", table_name="creative_board_edges")
    op.drop_table("creative_board_edges")
    op.drop_index("ix_creative_board_items_board", table_name="creative_board_items")
    op.drop_table("creative_board_items")
    op.drop_index("ix_creative_boards_project", table_name="creative_boards")
    op.drop_index("ix_creative_boards_user_id", table_name="creative_boards")
    op.drop_table("creative_boards")

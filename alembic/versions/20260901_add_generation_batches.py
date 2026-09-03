"""add durable generation batches

Revision ID: 20260901_generation_batches
Revises: 20260901_endpoint_declaration
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_generation_batches"
down_revision: str | Sequence[str] | None = "20260901_endpoint_declaration"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "generation_batches",
        sa.Column("batch_id", sa.String(), nullable=False),
        sa.Column("project_name", sa.String(), nullable=False),
        sa.Column("admission_state", sa.String(), nullable=False),
        sa.Column("items_json", sa.Text(), nullable=False),
        sa.Column("task_ids_json", sa.Text(), nullable=False),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="default"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("batch_id"),
    )
    op.create_index(
        "idx_generation_batches_user_project_updated",
        "generation_batches",
        ["user_id", "project_name", "updated_at"],
        unique=False,
    )
    op.create_index("ix_generation_batches_user_id", "generation_batches", ["user_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_generation_batches_user_id", table_name="generation_batches")
    op.drop_index("idx_generation_batches_user_project_updated", table_name="generation_batches")
    op.drop_table("generation_batches")

"""add endpoint declaration to custom provider model

Revision ID: 20260901_endpoint_declaration
Revises: 20260830_merge_all_heads
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260901_endpoint_declaration"
down_revision: str | Sequence[str] | None = "20260830_merge_all_heads"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("custom_provider_model", schema=None) as batch_op:
        batch_op.add_column(sa.Column("endpoint_declaration", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("custom_provider_model", schema=None) as batch_op:
        batch_op.drop_column("endpoint_declaration")

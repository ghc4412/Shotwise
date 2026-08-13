"""add is_enabled to custom_provider

Revision ID: ec24f1fe799d
Revises: a6ef68ef629e
Create Date: 2026-08-13 17:59:34.650521

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ec24f1fe799d"
down_revision: str | Sequence[str] | None = "a6ef68ef629e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """给 custom_provider 增加供应商级启用开关列，存量行默认启用。"""
    with op.batch_alter_table("custom_provider", schema=None) as batch_op:
        batch_op.add_column(sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.true()))


def downgrade() -> None:
    """回滚：移除 is_enabled 列。"""
    with op.batch_alter_table("custom_provider", schema=None) as batch_op:
        batch_op.drop_column("is_enabled")

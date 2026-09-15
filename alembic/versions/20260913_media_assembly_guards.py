"""Add preview and explicit render-confirmation guards to assembly plans."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_media_assembly_guards"
down_revision: str | Sequence[str] | None = "20260913_media_assembly"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assembly_plans", sa.Column("preview_revision_number", sa.Integer(), nullable=True))
    op.add_column("assembly_plans", sa.Column("preview_ready_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("assembly_plans", sa.Column("render_confirmed_by", sa.String(length=128), nullable=True))
    op.add_column("assembly_plans", sa.Column("render_confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("assembly_plans", "render_confirmed_at")
    op.drop_column("assembly_plans", "render_confirmed_by")
    op.drop_column("assembly_plans", "preview_ready_at")
    op.drop_column("assembly_plans", "preview_revision_number")

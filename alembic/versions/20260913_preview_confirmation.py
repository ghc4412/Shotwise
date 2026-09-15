"""Add authenticated preview confirmation fields to assembly plans."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_preview_confirmation"
down_revision: str | Sequence[str] | None = "20260913_render_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assembly_plans", sa.Column("preview_confirmed_by", sa.String(length=128), nullable=True))
    op.add_column("assembly_plans", sa.Column("preview_confirmed_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("assembly_plans", "preview_confirmed_at")
    op.drop_column("assembly_plans", "preview_confirmed_by")

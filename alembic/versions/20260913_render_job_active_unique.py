"""Prevent duplicate active preview or final jobs for one plan revision."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_render_job_active_unique"
down_revision: str | Sequence[str] | None = "20260913_preview_confirmation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "uq_render_jobs_active_plan_revision_kind",
        "render_jobs",
        ["plan_id", "revision_number", "kind"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )


def downgrade() -> None:
    op.drop_index("uq_render_jobs_active_plan_revision_kind", table_name="render_jobs")

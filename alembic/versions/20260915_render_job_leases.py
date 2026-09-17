"""Add durable worker lease and progress fields to render jobs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260915_render_job_leases"
down_revision: str | Sequence[str] | None = "20260914_publish_job_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("render_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("progress", sa.Float(), nullable=False, server_default="0"))
        batch_op.add_column(sa.Column("progress_stage", sa.String(length=32), nullable=False, server_default="queued"))
        batch_op.add_column(sa.Column("worker_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True))

    op.create_index("ix_render_jobs_heartbeat", "render_jobs", ["status", "heartbeat_at"])
    op.drop_index("uq_render_jobs_active_plan_revision_kind", table_name="render_jobs")
    op.create_index(
        "uq_render_jobs_active_plan_revision_kind",
        "render_jobs",
        ["plan_id", "revision_number", "kind"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
        postgresql_where=sa.text("status IN ('queued', 'running', 'cancelling')"),
    )


def downgrade() -> None:
    op.drop_index("uq_render_jobs_active_plan_revision_kind", table_name="render_jobs")
    op.create_index(
        "uq_render_jobs_active_plan_revision_kind",
        "render_jobs",
        ["plan_id", "revision_number", "kind"],
        unique=True,
        sqlite_where=sa.text("status IN ('queued', 'running')"),
        postgresql_where=sa.text("status IN ('queued', 'running')"),
    )
    op.drop_index("ix_render_jobs_heartbeat", table_name="render_jobs")

    with op.batch_alter_table("render_jobs", schema=None) as batch_op:
        batch_op.drop_column("cancel_requested_at")
        batch_op.drop_column("heartbeat_at")
        batch_op.drop_column("worker_id")
        batch_op.drop_column("progress_stage")
        batch_op.drop_column("progress")

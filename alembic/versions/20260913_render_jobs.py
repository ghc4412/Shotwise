"""Create persistent preview render jobs and artifacts."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_render_jobs"
down_revision: str | Sequence[str] | None = "20260913_media_assembly_guards"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "render_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), server_default="preview", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["assembly_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_render_jobs_plan_id", "render_jobs", ["plan_id"])
    op.create_index("ix_render_jobs_user_id", "render_jobs", ["user_id"])
    op.create_index("ix_render_jobs_status", "render_jobs", ["status"])
    op.create_index(
        "ix_render_jobs_user_project_status",
        "render_jobs",
        ["user_id", "project_name", "status"],
    )
    op.create_index("ix_render_jobs_plan_revision", "render_jobs", ["plan_id", "revision_number"])

    op.create_table(
        "render_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("render_job_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=24), server_default="preview", nullable=False),
        sa.Column("relative_path", sa.String(length=1000), nullable=False),
        sa.Column("mime_type", sa.String(length=128), server_default="video/mp4", nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["render_job_id"], ["render_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_render_artifacts_render_job_id", "render_artifacts", ["render_job_id"])
    op.create_index("ix_render_artifacts_plan_id", "render_artifacts", ["plan_id"])
    op.create_index("ix_render_artifacts_user_id", "render_artifacts", ["user_id"])
    op.create_index("ix_render_artifacts_job_kind", "render_artifacts", ["render_job_id", "kind"])
    op.create_index("ix_render_artifacts_user_project", "render_artifacts", ["user_id", "project_name"])


def downgrade() -> None:
    op.drop_index("ix_render_artifacts_user_project", table_name="render_artifacts")
    op.drop_index("ix_render_artifacts_job_kind", table_name="render_artifacts")
    op.drop_index("ix_render_artifacts_user_id", table_name="render_artifacts")
    op.drop_index("ix_render_artifacts_plan_id", table_name="render_artifacts")
    op.drop_index("ix_render_artifacts_render_job_id", table_name="render_artifacts")
    op.drop_table("render_artifacts")
    op.drop_index("ix_render_jobs_plan_revision", table_name="render_jobs")
    op.drop_index("ix_render_jobs_user_project_status", table_name="render_jobs")
    op.drop_index("ix_render_jobs_status", table_name="render_jobs")
    op.drop_index("ix_render_jobs_user_id", table_name="render_jobs")
    op.drop_index("ix_render_jobs_plan_id", table_name="render_jobs")
    op.drop_table("render_jobs")

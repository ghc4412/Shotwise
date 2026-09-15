"""Create platform-independent publish jobs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_publish_jobs"
down_revision: str | Sequence[str] | None = "20260914_render_review_snapshots"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publish_jobs",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("review_snapshot_id", sa.String(length=36), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("destination_json", sa.Text(), server_default="{}", nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=False),
        sa.Column("request_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), server_default="queued", nullable=False),
        sa.Column("attempt", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="3", nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["assembly_plans.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["artifact_id"], ["render_artifacts.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["review_snapshot_id"], ["render_review_snapshots.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_publish_jobs_user_idempotency"),
    )
    op.create_index("ix_publish_jobs_user_id", "publish_jobs", ["user_id"])
    op.create_index("ix_publish_jobs_plan_id", "publish_jobs", ["plan_id"])
    op.create_index("ix_publish_jobs_artifact_id", "publish_jobs", ["artifact_id"])
    op.create_index("ix_publish_jobs_status", "publish_jobs", ["status"])
    op.create_index("ix_publish_jobs_user_status", "publish_jobs", ["user_id", "status"])
    op.create_index("ix_publish_jobs_plan_revision", "publish_jobs", ["plan_id", "revision_number"])


def downgrade() -> None:
    op.drop_index("ix_publish_jobs_plan_revision", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_user_status", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_status", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_artifact_id", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_plan_id", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_user_id", table_name="publish_jobs")
    op.drop_table("publish_jobs")

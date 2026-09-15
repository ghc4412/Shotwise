"""Persist deterministic final render review snapshots."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_render_review_snapshots"
down_revision: str | Sequence[str] | None = "20260913_render_job_active_unique"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "render_review_snapshots",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("artifact_id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("revision_number", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("artifact_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("checks_json", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("confirmed_by", sa.String(length=128), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["artifact_id"], ["render_artifacts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_render_review_snapshots_artifact_id", "render_review_snapshots", ["artifact_id"])
    op.create_index("ix_render_review_snapshots_plan_id", "render_review_snapshots", ["plan_id"])
    op.create_index("ix_render_review_snapshots_user_id", "render_review_snapshots", ["user_id"])
    op.create_index(
        "ix_render_review_snapshots_artifact_created",
        "render_review_snapshots",
        ["artifact_id", "created_at"],
    )
    op.create_index(
        "ix_render_review_snapshots_user_project",
        "render_review_snapshots",
        ["user_id", "project_name"],
    )


def downgrade() -> None:
    op.drop_index("ix_render_review_snapshots_user_project", table_name="render_review_snapshots")
    op.drop_index("ix_render_review_snapshots_artifact_created", table_name="render_review_snapshots")
    op.drop_index("ix_render_review_snapshots_user_id", table_name="render_review_snapshots")
    op.drop_index("ix_render_review_snapshots_plan_id", table_name="render_review_snapshots")
    op.drop_index("ix_render_review_snapshots_artifact_id", table_name="render_review_snapshots")
    op.drop_table("render_review_snapshots")

"""create media assembly plan tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260913_media_assembly"
down_revision: str | Sequence[str] | None = "20260911_agent_memory_indexes"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "assembly_plans",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=False),
        sa.Column("scope", sa.String(length=32), nullable=False, server_default="episode"),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False, server_default="draft"),
        sa.Column("current_revision_number", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("current_source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_assembly_plans_user_id", "assembly_plans", ["user_id"])
    op.create_index("ix_assembly_plans_project_name", "assembly_plans", ["project_name"])
    op.create_index("ix_assembly_plans_status", "assembly_plans", ["status"])
    op.create_index(
        "ix_assembly_plans_user_project_status",
        "assembly_plans",
        ["user_id", "project_name", "status"],
    )

    op.create_table(
        "assembly_plan_revisions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("plan_id", sa.String(length=36), nullable=False),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("source_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("source_snapshot_json", sa.Text(), nullable=False),
        sa.Column("timeline_json", sa.Text(), nullable=False),
        sa.Column("audio_json", sa.Text(), nullable=False),
        sa.Column("subtitle_json", sa.Text(), nullable=False),
        sa.Column("packaging_json", sa.Text(), nullable=False),
        sa.Column("output_profile_json", sa.Text(), nullable=False),
        sa.Column("validation_json", sa.Text(), nullable=False),
        sa.Column("created_by", sa.String(length=128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["plan_id"], ["assembly_plans.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("plan_id", "version_number", name="uq_assembly_plan_revision_number"),
    )
    op.create_index("ix_assembly_plan_revisions_plan_id", "assembly_plan_revisions", ["plan_id"])
    op.create_index(
        "ix_assembly_plan_revisions_plan_created",
        "assembly_plan_revisions",
        ["plan_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_assembly_plan_revisions_plan_created", table_name="assembly_plan_revisions")
    op.drop_index("ix_assembly_plan_revisions_plan_id", table_name="assembly_plan_revisions")
    op.drop_table("assembly_plan_revisions")
    op.drop_index("ix_assembly_plans_user_project_status", table_name="assembly_plans")
    op.drop_index("ix_assembly_plans_status", table_name="assembly_plans")
    op.drop_index("ix_assembly_plans_project_name", table_name="assembly_plans")
    op.drop_index("ix_assembly_plans_user_id", table_name="assembly_plans")
    op.drop_table("assembly_plans")

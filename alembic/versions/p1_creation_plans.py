"""add immutable Creation Plan snapshots and anonymous compatibility events

Revision ID: p1creation001
Revises: d2workflow002
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p1creation001"
down_revision: str | Sequence[str] | None = "d2workflow002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_plans",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("user_id", sa.String(128), nullable=False),
        sa.Column("workspace_id", sa.String(128), nullable=False),
        sa.Column("project_id", sa.String(200), nullable=False),
        sa.Column("creation_skill_version_id", sa.String(128), nullable=False),
        sa.Column("skill_id", sa.String(128), nullable=False),
        sa.Column("workflow_revision", sa.String(128), nullable=False),
        sa.Column("fingerprint", sa.String(64), nullable=False, unique=True),
        sa.Column("idempotency_key", sa.String(256), nullable=False),
        sa.Column("project_snapshot_json", sa.Text(), nullable=False),
        sa.Column("resource_ids_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("parameters_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(24), nullable=False, server_default="previewed"),
        sa.Column("workflow_run_id", sa.String(36), sa.ForeignKey("workflow_runs.id", ondelete="SET NULL")),
        sa.Column("created_by", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("cancelled_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_creation_plan_idempotency"),
    )
    op.create_index("ix_creation_plans_user_id", "creation_plans", ["user_id"])
    op.create_index("ix_creation_plans_project_id", "creation_plans", ["project_id"])
    op.create_index("ix_creation_plans_workflow_run_id", "creation_plans", ["workflow_run_id"])
    op.create_index("ix_creation_plans_project_status", "creation_plans", ["project_id", "status"])
    op.create_table(
        "creation_compatibility_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("creation_skill_version_id", sa.String(128), nullable=False),
        sa.Column("project_content_mode", sa.String(32), nullable=False),
        sa.Column("project_generation_mode", sa.String(32), nullable=False),
        sa.Column("resource_types_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("reason", sa.String(128), nullable=False),
        sa.Column("outcome", sa.String(32), nullable=False, server_default="unresolved"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_creation_compatibility_events_skill_version_id",
        "creation_compatibility_events",
        ["creation_skill_version_id"],
    )
    op.create_index(
        "ix_creation_compatibility_events_project_generation_mode",
        "creation_compatibility_events",
        ["project_generation_mode"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_creation_compatibility_events_project_generation_mode", table_name="creation_compatibility_events"
    )
    op.drop_index("ix_creation_compatibility_events_skill_version_id", table_name="creation_compatibility_events")
    op.drop_table("creation_compatibility_events")
    op.drop_index("ix_creation_plans_project_status", table_name="creation_plans")
    op.drop_index("ix_creation_plans_workflow_run_id", table_name="creation_plans")
    op.drop_index("ix_creation_plans_project_id", table_name="creation_plans")
    op.drop_index("ix_creation_plans_user_id", table_name="creation_plans")
    op.drop_table("creation_plans")

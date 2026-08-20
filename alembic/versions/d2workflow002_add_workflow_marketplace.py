"""add workflow marketplace and episode budget contract

Revision ID: d2workflow002
Revises: c3da32c70e98
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d2workflow002"
down_revision: str | Sequence[str] | None = "c3da32c70e98"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("workflow_revisions") as batch:
        batch.add_column(sa.Column("content_mode", sa.String(32), nullable=False, server_default="drama"))
        batch.add_column(sa.Column("generation_mode", sa.String(32), nullable=False, server_default="storyboard"))
        batch.add_column(sa.Column("input_schema_json", sa.Text(), nullable=False, server_default="{}"))
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.add_column(sa.Column("input_schema_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("output_schema_json", sa.Text(), nullable=False, server_default="{}"))
        batch.add_column(sa.Column("executor_id", sa.String(128), nullable=False, server_default="builtin"))
        batch.add_column(sa.Column("required_capabilities_json", sa.Text(), nullable=False, server_default="[]"))
        batch.add_column(sa.Column("estimated_cost", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("cache_policy", sa.String(32), nullable=False, server_default="reuse"))
    with op.batch_alter_table("workflow_runs") as batch:
        batch.add_column(sa.Column("episode_id", sa.String(128)))
        batch.add_column(sa.Column("budget_limit", sa.Float()))
        batch.add_column(sa.Column("spent_amount", sa.Float(), nullable=False, server_default="0"))
        batch.add_column(sa.Column("reserved_amount", sa.Float(), nullable=False, server_default="0"))
        batch.create_index("ix_workflow_runs_episode_id", ["episode_id"])

    op.create_table(
        "workflow_templates",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False, server_default=""),
        sa.Column("cover_ref", sa.String(500)),
        sa.Column("template_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("draft_revision_id", sa.String(36)),
        sa.Column("published_revision_id", sa.String(36)),
        sa.Column("contract_json", sa.Text(), nullable=False, server_default="{}"),
        sa.Column("submitted_at", sa.DateTime(timezone=True)),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["draft_revision_id"], ["workflow_revisions.id"]),
        sa.ForeignKeyConstraint(["published_revision_id"], ["workflow_revisions.id"]),
    )
    op.create_index("ix_workflow_templates_status", "workflow_templates", ["status"])
    op.create_index("ix_workflow_templates_template_type", "workflow_templates", ["template_type"])
    op.create_index("ix_workflow_templates_user_id", "workflow_templates", ["user_id"])
    op.create_table(
        "workflow_marketplace_reviews",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("template_id", sa.String(36), nullable=False),
        sa.Column("revision_id", sa.String(36), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("comment", sa.Text(), nullable=False),
        sa.Column("reviewer_id", sa.String(128), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["template_id"], ["workflow_templates.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["revision_id"], ["workflow_revisions.id"]),
    )
    op.create_index("ix_workflow_marketplace_reviews_template_id", "workflow_marketplace_reviews", ["template_id"])
    op.create_index(
        "ix_workflow_marketplace_reviews_template_created", "workflow_marketplace_reviews", ["template_id", "created_at"]
    )
    op.create_table(
        "workflow_usage_stats",
        sa.Column("template_id", sa.String(36), primary_key=True),
        sa.Column("views", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("derivations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("successful_run_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
        sa.Column("total_duration_seconds", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rating_total", sa.Float(), nullable=False, server_default="0"),
        sa.Column("rating_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["template_id"], ["workflow_templates.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("workflow_usage_stats")
    op.drop_index("ix_workflow_marketplace_reviews_template_created", table_name="workflow_marketplace_reviews")
    op.drop_index("ix_workflow_marketplace_reviews_template_id", table_name="workflow_marketplace_reviews")
    op.drop_table("workflow_marketplace_reviews")
    op.drop_index("ix_workflow_templates_user_id", table_name="workflow_templates")
    op.drop_index("ix_workflow_templates_template_type", table_name="workflow_templates")
    op.drop_index("ix_workflow_templates_status", table_name="workflow_templates")
    op.drop_table("workflow_templates")
    with op.batch_alter_table("workflow_runs") as batch:
        batch.drop_index("ix_workflow_runs_episode_id")
        batch.drop_column("reserved_amount")
        batch.drop_column("spent_amount")
        batch.drop_column("budget_limit")
        batch.drop_column("episode_id")
    with op.batch_alter_table("workflow_nodes") as batch:
        batch.drop_column("cache_policy")
        batch.drop_column("estimated_cost")
        batch.drop_column("required_capabilities_json")
        batch.drop_column("executor_id")
        batch.drop_column("output_schema_json")
        batch.drop_column("input_schema_json")
    with op.batch_alter_table("workflow_revisions") as batch:
        batch.drop_column("input_schema_json")
        batch.drop_column("generation_mode")
        batch.drop_column("content_mode")

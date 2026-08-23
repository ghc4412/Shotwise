"""persist the official Creation Skill catalog and frozen releases

Revision ID: p3skill001
Revises: p2creative001
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p3skill001"
down_revision: str | Sequence[str] | None = "p2creative001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "creation_skill_definitions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("official", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_creation_skill_definitions_active", "creation_skill_definitions", ["active"])
    op.create_table(
        "creation_skill_versions",
        sa.Column("id", sa.String(128), primary_key=True),
        sa.Column("skill_id", sa.String(128), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("workflow_template_revision_alias", sa.String(200), nullable=False),
        sa.Column("expected_outputs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("review_required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("estimated_cost_hint", sa.String(128)),
        sa.Column("status", sa.String(24), nullable=False, server_default="published"),
        sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["skill_id"], ["creation_skill_definitions.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("skill_id", "version", name="uq_creation_skill_version_number"),
    )
    op.create_index("ix_creation_skill_versions_skill_id", "creation_skill_versions", ["skill_id"])
    op.create_index("ix_creation_skill_versions_status", "creation_skill_versions", ["status"])
    op.create_table(
        "creation_skill_compatibilities",
        sa.Column("skill_version_id", sa.String(128), primary_key=True),
        sa.Column("content_modes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("generation_modes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("required_inputs_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("scopes_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("grid_storyboards_json", sa.Text()),
        sa.ForeignKeyConstraint(["skill_version_id"], ["creation_skill_versions.id"], ondelete="CASCADE"),
    )


def downgrade() -> None:
    op.drop_table("creation_skill_compatibilities")
    op.drop_index("ix_creation_skill_versions_status", table_name="creation_skill_versions")
    op.drop_index("ix_creation_skill_versions_skill_id", table_name="creation_skill_versions")
    op.drop_table("creation_skill_versions")
    op.drop_index("ix_creation_skill_definitions_active", table_name="creation_skill_definitions")
    op.drop_table("creation_skill_definitions")

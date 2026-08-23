"""Create durable MediaAsset index tables without moving legacy files."""

import sqlalchemy as sa

from alembic import op

revision = "p5_media_assets"
down_revision = "p4_creation_skill_workflow_binding"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "media_assets",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("kind", sa.String(32), nullable=False),
        sa.Column("original_name", sa.String(512), nullable=False),
        sa.Column("mime_type", sa.String(255)),
        sa.Column("extension", sa.String(32), nullable=False),
        sa.Column("physical_path", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("fingerprint", sa.String(128), nullable=False),
        sa.Column("origin", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.Column("width", sa.Integer()),
        sa.Column("height", sa.Integer()),
        sa.Column("duration_seconds", sa.Float()),
        sa.Column("workflow_run_id", sa.String(255)),
        sa.Column("workflow_node_key", sa.String(255)),
        sa.Column("provider_id", sa.String(255)),
        sa.Column("model_id", sa.String(255)),
        sa.Column("prompt_snapshot", sa.Text()),
        sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "project_id", "physical_path", "fingerprint", name="uq_media_assets_project_path_fingerprint"
        ),
    )
    op.create_index("ix_media_assets_project_kind", "media_assets", ["project_id", "kind"])
    op.create_index("ix_media_assets_project_origin", "media_assets", ["project_id", "origin"])
    op.create_index("ix_media_assets_project_workflow", "media_assets", ["project_id", "workflow_run_id"])
    op.create_table(
        "media_bindings",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("media_asset_id", sa.String(36), nullable=False),
        sa.Column("project_id", sa.String(255), nullable=False),
        sa.Column("binding_kind", sa.String(32), nullable=False),
        sa.Column("target_id", sa.String(255)),
        sa.Column("purpose", sa.String(128), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "media_asset_id",
            "project_id",
            "binding_kind",
            "target_id",
            "purpose",
            name="uq_media_bindings_semantic_reference",
        ),
    )
    op.create_index("ix_media_bindings_project_target", "media_bindings", ["project_id", "binding_kind", "target_id"])
    op.create_table(
        "media_derivations",
        sa.Column("id", sa.String(36), nullable=False),
        sa.Column("parent_media_asset_id", sa.String(36), nullable=False),
        sa.Column("child_media_asset_id", sa.String(36), nullable=False),
        sa.Column("operation", sa.String(32), nullable=False),
        sa.Column("created_at", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(["parent_media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["child_media_asset_id"], ["media_assets.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "parent_media_asset_id",
            "child_media_asset_id",
            "operation",
            name="uq_media_derivations_parent_child_operation",
        ),
    )
    op.create_index("ix_media_derivations_child", "media_derivations", ["child_media_asset_id"])


def downgrade() -> None:
    op.drop_index("ix_media_derivations_child", table_name="media_derivations")
    op.drop_table("media_derivations")
    op.drop_index("ix_media_bindings_project_target", table_name="media_bindings")
    op.drop_table("media_bindings")
    op.drop_index("ix_media_assets_project_workflow", table_name="media_assets")
    op.drop_index("ix_media_assets_project_origin", table_name="media_assets")
    op.drop_index("ix_media_assets_project_kind", table_name="media_assets")
    op.drop_table("media_assets")

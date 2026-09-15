"""add Agent long-term memory tables."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260911_agent_memory"
down_revision: str | Sequence[str] | None = "20260903_agent_credential_protocol"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _columns() -> list[sa.Column]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(), nullable=False, server_default="default"),
        sa.Column("scope", sa.String(length=16), nullable=False),
        sa.Column("project_name", sa.String(length=200), nullable=True),
        sa.Column("category", sa.String(length=32), nullable=False, server_default="other"),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="user"),
        sa.Column("confirmed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("source_session_id", sa.String(length=128), nullable=True),
        sa.Column("source_message_id", sa.String(length=128), nullable=True),
        sa.Column("metadata_json", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
    ]


def upgrade() -> None:
    op.create_table("memory_entries", *_columns(), sa.PrimaryKeyConstraint("id"))
    op.create_index(
        "ix_memory_entries_user_scope_project",
        "memory_entries",
        ["user_id", "scope", "project_name"],
    )
    op.create_index(
        "ix_memory_entries_user_confirmed",
        "memory_entries",
        ["user_id", "confirmed", "updated_at"],
    )

    candidate_columns = _columns()
    for column in candidate_columns:
        if column.name == "source":
            column.server_default = sa.text("'agent'")
        elif column.name == "confirmed":
            column.server_default = sa.false()
    candidate_columns.insert(8, sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"))
    op.create_table("memory_candidates", *candidate_columns, sa.PrimaryKeyConstraint("id"))
    op.create_index(
        "ix_memory_candidates_user_scope_project",
        "memory_candidates",
        ["user_id", "scope", "project_name"],
    )
    op.create_index(
        "ix_memory_candidates_user_status",
        "memory_candidates",
        ["user_id", "status", "updated_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_memory_candidates_user_status", table_name="memory_candidates")
    op.drop_index("ix_memory_candidates_user_scope_project", table_name="memory_candidates")
    op.drop_table("memory_candidates")
    op.drop_index("ix_memory_entries_user_confirmed", table_name="memory_entries")
    op.drop_index("ix_memory_entries_user_scope_project", table_name="memory_entries")
    op.drop_table("memory_entries")

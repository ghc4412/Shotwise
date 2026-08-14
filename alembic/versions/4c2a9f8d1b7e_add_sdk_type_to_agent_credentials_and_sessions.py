"""add sdk_type to agent credentials and dual-sdk columns to agent sessions

Revision ID: 4c2a9f8d1b7e
Revises: ec24f1fe799d
Create Date: 2026-08-14 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c2a9f8d1b7e"
down_revision: str | Sequence[str] | None = "ec24f1fe799d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    # agent_anthropic_credentials: sdk_type 列 + active 唯一约束扩展到 (user, sdk_type)
    with op.batch_alter_table("agent_anthropic_credentials", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sdk_type", sa.String(length=16), nullable=False, server_default="claude"))
        batch_op.drop_index("uq_agent_credential_one_active_per_user")
        batch_op.create_index(
            "uq_agent_credential_one_active_per_user_sdk",
            ["user_id", "sdk_type"],
            unique=True,
            postgresql_where=sa.text("is_active"),
            sqlite_where=sa.text("is_active = 1"),
        )

    # agent_sessions: 当前活跃 SDK 类型 + Claude 续接 id（OpenAI Agents SDK 的会话
    # 历史由 SQLiteSession 按 sdk_session_id 持久化，无需额外列）
    with op.batch_alter_table("agent_sessions", schema=None) as batch_op:
        batch_op.add_column(sa.Column("sdk_type", sa.String(length=16), server_default="claude", nullable=False))
        batch_op.add_column(sa.Column("claude_resume_id", sa.String(), nullable=True))
        batch_op.create_index("idx_agent_sessions_sdk_type", ["sdk_type"], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("agent_sessions", schema=None) as batch_op:
        batch_op.drop_index("idx_agent_sessions_sdk_type")
        batch_op.drop_column("claude_resume_id")
        batch_op.drop_column("sdk_type")

    with op.batch_alter_table("agent_anthropic_credentials", schema=None) as batch_op:
        batch_op.drop_index("uq_agent_credential_one_active_per_user_sdk")
        batch_op.create_index(
            "uq_agent_credential_one_active_per_user",
            ["user_id"],
            unique=True,
            postgresql_where=sa.text("is_active"),
            sqlite_where=sa.text("is_active = 1"),
        )
        batch_op.drop_column("sdk_type")

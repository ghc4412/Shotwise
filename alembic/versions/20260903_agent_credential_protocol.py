"""add Agent credential transport protocol"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260903_agent_credential_protocol"
down_revision: str | Sequence[str] | None = "20260901_generation_batches"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "agent_anthropic_credentials",
        sa.Column("protocol", sa.String(length=32), nullable=False, server_default="chat_completions"),
    )
    op.execute(
        sa.text(
            "UPDATE agent_anthropic_credentials "
            "SET protocol = CASE WHEN sdk_type = 'claude' THEN 'anthropic_messages' ELSE 'chat_completions' END"
        )
    )


def downgrade() -> None:
    op.drop_column("agent_anthropic_credentials", "protocol")

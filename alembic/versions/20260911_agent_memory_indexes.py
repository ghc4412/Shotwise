"""add ownership indexes for Agent long-term memory tables."""

from collections.abc import Sequence

from alembic import op

revision: str = "20260911_agent_memory_indexes"
down_revision: str | Sequence[str] | None = "20260911_agent_memory"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index("ix_memory_entries_user_id", "memory_entries", ["user_id"])
    op.create_index("ix_memory_candidates_user_id", "memory_candidates", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_memory_candidates_user_id", table_name="memory_candidates")
    op.drop_index("ix_memory_entries_user_id", table_name="memory_entries")

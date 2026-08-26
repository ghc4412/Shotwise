"""Merge the creation-skill and workflow-persistence migration branches."""

from collections.abc import Sequence

revision: str = "wf4_merge_heads"
down_revision: str | Sequence[str] | None = ("p2creative002", "wf3_workflow_persistence")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge the two existing heads without changing the schema."""


def downgrade() -> None:
    """Re-expose the two branches when downgrading past the merge."""

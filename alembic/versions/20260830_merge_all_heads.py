"""merge the two independent migration heads

Revision ID: 20260830_merge_all_heads
Revises: b3f9c07ae214, p2creative003
"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "20260830_merge_all_heads"
down_revision: str | Sequence[str] | None = (
    "b3f9c07ae214",
    "p2creative003",
)
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Merge migration branches after all branch-specific changes have run."""


def downgrade() -> None:
    """Re-expose the three independent heads when downgrading past the merge."""

"""merge workflow contract and provider_endpoint heads

Revision ID: 8b8a38ba7c17
Revises: c1shotwise001, c4a91f7d2b18
Create Date: 2026-08-11 02:18:40.647192

"""
from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = '8b8a38ba7c17'
down_revision: str | Sequence[str] | None = ('c1shotwise001', 'c4a91f7d2b18')
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass

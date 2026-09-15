"""Widen Alembic's revision storage before long revision identifiers are applied."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "p4versionwidth"
down_revision: str | Sequence[str] | None = "p3skill001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_VERSION_COLUMN_LENGTH = 128


def upgrade() -> None:
    with op.batch_alter_table("alembic_version", schema=None) as batch_op:
        batch_op.alter_column(
            "version_num",
            existing_type=sa.String(length=32),
            type_=sa.String(length=_VERSION_COLUMN_LENGTH),
            existing_nullable=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("alembic_version", schema=None) as batch_op:
        batch_op.alter_column(
            "version_num",
            existing_type=sa.String(length=_VERSION_COLUMN_LENGTH),
            type_=sa.String(length=32),
            existing_nullable=False,
        )

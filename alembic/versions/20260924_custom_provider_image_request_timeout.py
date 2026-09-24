"""add image_request_timeout_seconds to custom_provider

Revision ID: 20260924_image_request_timeout
Revises: 20260914_publish_job_leases
Create Date: 2026-09-24

Additive nullable per-provider image request timeout with a DB-level strictly
positive CHECK constraint. No backfill: NULL means "unset" and the image
backend then falls back to IMAGE_REQUEST_TIMEOUT_SECONDS / its built-in
default, so existing rows keep their current behaviour. The check enforces the
NULL-or-positive contract at the storage layer, so repo writes and manual SQL
cannot persist 0 or a negative timeout (which the SDK would treat as an
already-expired request rather than "no timeout").
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "20260924_image_request_timeout"
down_revision: str | Sequence[str] | None = "20260914_publish_job_leases"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table("custom_provider", schema=None) as batch_op:
        batch_op.add_column(sa.Column("image_request_timeout_seconds", sa.Float(), nullable=True))
        batch_op.create_check_constraint(
            "ck_custom_provider_image_request_timeout_positive",
            "image_request_timeout_seconds IS NULL OR image_request_timeout_seconds > 0",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table("custom_provider", schema=None) as batch_op:
        batch_op.drop_constraint("ck_custom_provider_image_request_timeout_positive", type_="check")
        batch_op.drop_column("image_request_timeout_seconds")

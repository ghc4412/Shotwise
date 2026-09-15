"""Add worker lease fields to publish jobs."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_publish_job_leases"
down_revision: str | Sequence[str] | None = "20260914_publishing_accounts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("worker_id", sa.String(length=128), nullable=True))
        batch_op.add_column(sa.Column("lease_until", sa.DateTime(timezone=True), nullable=True))

    op.create_index(
        "ix_publish_jobs_lease",
        "publish_jobs",
        ["status", "lease_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_publish_jobs_lease", table_name="publish_jobs")

    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.drop_column("lease_until")
        batch_op.drop_column("worker_id")

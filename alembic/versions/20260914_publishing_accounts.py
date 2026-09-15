"""Persist publishing accounts and external publish-job state."""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260914_publishing_accounts"
down_revision: str | Sequence[str] | None = "20260914_publish_jobs"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "publishing_accounts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=128), nullable=False),
        sa.Column("platform", sa.String(length=64), nullable=False),
        sa.Column("platform_account_id", sa.String(length=256), nullable=False),
        sa.Column("account_name", sa.String(length=256), nullable=False),
        sa.Column("avatar_url", sa.Text(), nullable=True),
        sa.Column("encrypted_access_token", sa.Text(), nullable=True),
        sa.Column("encrypted_refresh_token", sa.Text(), nullable=True),
        sa.Column("token_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("scopes_json", sa.Text(), server_default="[]", nullable=False),
        sa.Column("encryption_key_version", sa.String(length=16), server_default="v1", nullable=False),
        sa.Column("status", sa.String(length=24), server_default="active", nullable=False),
        sa.Column("last_refresh_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "platform",
            "platform_account_id",
            name="uq_publishing_account_identity",
        ),
    )
    op.create_index("ix_publishing_accounts_user_id", "publishing_accounts", ["user_id"])
    op.create_index(
        "ix_publishing_accounts_user_platform",
        "publishing_accounts",
        ["user_id", "platform"],
    )
    op.create_index("ix_publishing_accounts_status", "publishing_accounts", ["user_id", "status"])

    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.add_column(sa.Column("account_id", sa.String(length=36), nullable=True))
        batch_op.add_column(sa.Column("external_content_id", sa.String(length=256), nullable=True))
        batch_op.add_column(sa.Column("external_status", sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column("next_poll_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column("last_polled_at", sa.DateTime(timezone=True), nullable=True))
        batch_op.create_foreign_key(
            "fk_publish_jobs_account_id",
            "publishing_accounts",
            ["account_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.alter_column("status", existing_type=sa.String(length=24), type_=sa.String(length=32))

    op.create_index("ix_publish_jobs_account_id", "publish_jobs", ["account_id"])
    op.create_index("ix_publish_jobs_poll", "publish_jobs", ["status", "next_poll_at"])


def downgrade() -> None:
    op.drop_index("ix_publish_jobs_poll", table_name="publish_jobs")
    op.drop_index("ix_publish_jobs_account_id", table_name="publish_jobs")

    with op.batch_alter_table("publish_jobs", schema=None) as batch_op:
        batch_op.drop_constraint("fk_publish_jobs_account_id", type_="foreignkey")
        batch_op.alter_column("status", existing_type=sa.String(length=32), type_=sa.String(length=24))
        batch_op.drop_column("last_polled_at")
        batch_op.drop_column("next_poll_at")
        batch_op.drop_column("external_status")
        batch_op.drop_column("external_content_id")
        batch_op.drop_column("account_id")

    op.drop_index("ix_publishing_accounts_status", table_name="publishing_accounts")
    op.drop_index("ix_publishing_accounts_user_platform", table_name="publishing_accounts")
    op.drop_index("ix_publishing_accounts_user_id", table_name="publishing_accounts")
    op.drop_table("publishing_accounts")

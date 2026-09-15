"""Platform-independent publish job persistence."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class PublishJob(Base):
    """A durable publish request bound to one confirmed final artifact."""

    __tablename__ = "publish_jobs"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_publish_jobs_user_idempotency"),
        Index("ix_publish_jobs_user_status", "user_id", "status"),
        Index("ix_publish_jobs_artifact", "artifact_id"),
        Index("ix_publish_jobs_plan_revision", "plan_id", "revision_number"),
        Index("ix_publish_jobs_poll", "status", "next_poll_at"),
        Index("ix_publish_jobs_lease", "status", "lease_until"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assembly_plans.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("render_artifacts.id", ondelete="RESTRICT"), nullable=False
    )
    review_snapshot_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("render_review_snapshots.id", ondelete="RESTRICT"), nullable=False
    )
    account_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("publishing_accounts.id", ondelete="SET NULL"), nullable=True, index=True
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    destination_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="{}")
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    external_content_id: Mapped[str | None] = mapped_column(String(256), nullable=True)
    external_status: Mapped[str | None] = mapped_column(String(64), nullable=True)
    next_poll_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    worker_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["PublishJob"]

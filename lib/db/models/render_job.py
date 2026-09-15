"""Persistent preview render jobs and their immutable output artifacts."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class RenderJob(Base):
    """A retryable deterministic render attempt for one assembly revision."""

    __tablename__ = "render_jobs"
    __table_args__ = (
        Index("ix_render_jobs_user_project_status", "user_id", "project_name", "status"),
        Index("ix_render_jobs_plan_revision", "plan_id", "revision_number"),
        Index(
            "uq_render_jobs_active_plan_revision_kind",
            "plan_id",
            "revision_number",
            "kind",
            unique=True,
            sqlite_where=text("status IN ('queued', 'running')"),
            postgresql_where=text("status IN ('queued', 'running')"),
        ),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assembly_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, server_default="preview")
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="queued", index=True)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="3")
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RenderArtifact(Base):
    """A validated file produced by a render job."""

    __tablename__ = "render_artifacts"
    __table_args__ = (
        Index("ix_render_artifacts_job_kind", "render_job_id", "kind"),
        Index("ix_render_artifacts_user_project", "user_id", "project_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    render_job_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("render_jobs.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False, server_default="preview")
    relative_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(128), nullable=False, server_default="video/mp4")
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    duration_seconds: Mapped[float] = mapped_column(nullable=False)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RenderReviewSnapshot(Base):
    """An immutable deterministic review result for one final artifact."""

    __tablename__ = "render_review_snapshots"
    __table_args__ = (
        Index("ix_render_review_snapshots_artifact_created", "artifact_id", "created_at"),
        Index("ix_render_review_snapshots_user_project", "user_id", "project_name"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    artifact_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("render_artifacts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    artifact_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False)
    checks_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = ["RenderArtifact", "RenderJob", "RenderReviewSnapshot"]

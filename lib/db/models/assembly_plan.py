"""Persistent media assembly plans and immutable revisions."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class AssemblyPlan(Base):
    """Mutable lifecycle envelope for a media assembly plan."""

    __tablename__ = "assembly_plans"
    __table_args__ = (Index("ix_assembly_plans_user_project_status", "user_id", "project_name", "status"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_name: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    scope: Mapped[str] = mapped_column(String(32), nullable=False, server_default="episode")
    episode_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="draft", index=True)
    current_revision_number: Mapped[int] = mapped_column(Integer, nullable=False, server_default="1")
    current_source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    preview_revision_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    preview_confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    preview_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    render_confirmed_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    render_confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class AssemblyPlanRevision(Base):
    """Immutable complete snapshot consumed by future preview/render workers."""

    __tablename__ = "assembly_plan_revisions"
    __table_args__ = (
        UniqueConstraint("plan_id", "version_number", name="uq_assembly_plan_revision_number"),
        Index("ix_assembly_plan_revisions_plan_created", "plan_id", "created_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    plan_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("assembly_plans.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    source_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    source_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    timeline_json: Mapped[str] = mapped_column(Text, nullable=False)
    audio_json: Mapped[str] = mapped_column(Text, nullable=False)
    subtitle_json: Mapped[str] = mapped_column(Text, nullable=False)
    packaging_json: Mapped[str] = mapped_column(Text, nullable=False)
    output_profile_json: Mapped[str] = mapped_column(Text, nullable=False)
    validation_json: Mapped[str] = mapped_column(Text, nullable=False)
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


__all__ = ["AssemblyPlan", "AssemblyPlanRevision"]

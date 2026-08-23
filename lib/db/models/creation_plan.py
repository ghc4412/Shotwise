"""Persistent Creation Plan and anonymous compatibility-event models."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class CreationPlanRecord(Base):
    """Immutable plan snapshot; lifecycle status is the only mutable state."""

    __tablename__ = "creation_plans"
    __table_args__ = (
        UniqueConstraint("user_id", "project_id", "idempotency_key", name="uq_creation_plan_idempotency"),
        Index("ix_creation_plans_project_status", "project_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(80), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    workspace_id: Mapped[str] = mapped_column(String(128), nullable=False)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    creation_skill_version_id: Mapped[str] = mapped_column(String(128), nullable=False)
    skill_id: Mapped[str] = mapped_column(String(128), nullable=False)
    workflow_revision: Mapped[str] = mapped_column(String(128), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    idempotency_key: Mapped[str] = mapped_column(String(256), nullable=False)
    project_snapshot_json: Mapped[str] = mapped_column(Text, nullable=False)
    resource_ids_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    parameters_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    preview_json: Mapped[str] = mapped_column(Text, nullable=False)
    estimated_cost: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="previewed")
    workflow_run_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_runs.id", ondelete="SET NULL"), index=True
    )
    created_by: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class CreationCompatibilityEvent(Base):
    """Anonymous product signal for a Skill/Project mode incompatibility."""

    __tablename__ = "creation_compatibility_events"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    creation_skill_version_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_content_mode: Mapped[str] = mapped_column(String(32), nullable=False)
    project_generation_mode: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    resource_types_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    reason: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False, default="unresolved")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

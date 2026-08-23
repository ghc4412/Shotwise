"""Persistent official Creation Skill definitions and frozen releases."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, utc_now


class CreationSkillDefinitionRecord(Base):
    """Stable public identity for an official Creation Skill."""

    __tablename__ = "creation_skill_definitions"

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True)
    official: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=utc_now, onupdate=utc_now
    )


class CreationSkillVersionRecord(Base):
    """Immutable published release of a Creation Skill."""

    __tablename__ = "creation_skill_versions"
    __table_args__ = (
        UniqueConstraint("skill_id", "version", name="uq_creation_skill_version_number"),
        CheckConstraint(
            "status <> 'published' OR (workflow_revision_id IS NOT NULL AND length(trim(workflow_revision_id)) > 0)",
            name="ck_creation_skill_version_published_workflow_revision",
        ),
    )

    id: Mapped[str] = mapped_column(String(128), primary_key=True)
    skill_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("creation_skill_definitions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    workflow_template_revision_alias: Mapped[str] = mapped_column(String(200), nullable=False)
    workflow_revision_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("workflow_revisions.id", ondelete="RESTRICT"), nullable=True
    )
    expected_outputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    review_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    estimated_cost_hint: Mapped[str | None] = mapped_column(String(128))
    status: Mapped[str] = mapped_column(String(24), nullable=False, default="published", index=True)
    frozen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreationSkillCompatibilityRecord(Base):
    """Compatibility rules attached to one frozen Skill release."""

    __tablename__ = "creation_skill_compatibilities"

    skill_version_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("creation_skill_versions.id", ondelete="CASCADE"), primary_key=True
    )
    content_modes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    generation_modes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    required_inputs_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    grid_storyboards_json: Mapped[str | None] = mapped_column(Text)

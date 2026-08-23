"""Durable MediaAsset index rows and semantic media relationships."""

from __future__ import annotations

from sqlalchemy import BigInteger, Boolean, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class MediaAsset(Base):
    __tablename__ = "media_assets"
    __table_args__ = (
        UniqueConstraint("project_id", "physical_path", "fingerprint", name="uq_media_assets_project_path_fingerprint"),
        Index("ix_media_assets_project_kind", "project_id", "kind"),
        Index("ix_media_assets_project_origin", "project_id", "origin"),
        Index("ix_media_assets_project_workflow", "project_id", "workflow_run_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    kind: Mapped[str] = mapped_column(String(32), nullable=False)
    original_name: Mapped[str] = mapped_column(String(512), nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    extension: Mapped[str] = mapped_column(String(32), nullable=False)
    physical_path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    origin: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)
    width: Mapped[int | None] = mapped_column(Integer)
    height: Mapped[int | None] = mapped_column(Integer)
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    workflow_run_id: Mapped[str | None] = mapped_column(String(255))
    workflow_node_key: Mapped[str | None] = mapped_column(String(255))
    provider_id: Mapped[str | None] = mapped_column(String(255))
    model_id: Mapped[str | None] = mapped_column(String(255))
    prompt_snapshot: Mapped[str | None] = mapped_column(Text)
    archived: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class MediaBinding(Base):
    __tablename__ = "media_bindings"
    __table_args__ = (
        UniqueConstraint(
            "media_asset_id",
            "project_id",
            "binding_kind",
            "target_id",
            "purpose",
            name="uq_media_bindings_semantic_reference",
        ),
        Index("ix_media_bindings_project_target", "project_id", "binding_kind", "target_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    project_id: Mapped[str] = mapped_column(String(255), nullable=False)
    binding_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str | None] = mapped_column(String(255))
    purpose: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)


class MediaDerivation(Base):
    __tablename__ = "media_derivations"
    __table_args__ = (
        UniqueConstraint(
            "parent_media_asset_id",
            "child_media_asset_id",
            "operation",
            name="uq_media_derivations_parent_child_operation",
        ),
        Index("ix_media_derivations_child", "child_media_asset_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    parent_media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    child_media_asset_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("media_assets.id", ondelete="CASCADE"), nullable=False
    )
    operation: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[str] = mapped_column(String(64), nullable=False)

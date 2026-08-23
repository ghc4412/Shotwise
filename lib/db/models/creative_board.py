"""ORM models for the semantic Creative Board, separate from FlowCanvas."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base


class CreativeBoard(Base):
    """A project-owned semantic canvas; it does not describe execution order."""

    __tablename__ = "creative_boards"
    __table_args__ = (Index("ix_creative_boards_project", "project_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    project_id: Mapped[str] = mapped_column(String(200), nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    viewport_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    display_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreativeBoardItem(Base):
    """A positioned reference to a project resource or creative operation."""

    __tablename__ = "creative_board_items"
    __table_args__ = (Index("ix_creative_board_items_board", "board_id"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    item_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    position_x: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    position_y: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    width: Mapped[int] = mapped_column(Integer, nullable=False, default=280)
    height: Mapped[int] = mapped_column(Integer, nullable=False, default=180)
    group_id: Mapped[str | None] = mapped_column(String(36))
    display_settings_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class CreativeBoardEdge(Base):
    """A semantic relation only; execution dependencies are deliberately absent."""

    __tablename__ = "creative_board_edges"
    __table_args__ = (
        UniqueConstraint("board_id", "source_item_id", "target_item_id", "relation", name="uq_creative_board_edge"),
        Index("ix_creative_board_edges_board", "board_id"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    board_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_boards.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_board_items.id", ondelete="CASCADE"), nullable=False
    )
    target_item_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("creative_board_items.id", ondelete="CASCADE"), nullable=False
    )
    relation: Mapped[str] = mapped_column(String(32), nullable=False)
    ordinal: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

"""Long-term Agent memory records and reviewable candidates."""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin, UserOwnedMixin


class MemoryEntry(TimestampMixin, UserOwnedMixin, Base):
    """A user-confirmed long-term memory item.

    ``scope=user`` is global to the owning user; ``scope=project`` is further
    isolated by ``project_name``.  Content is always reference material and is
    never treated as an instruction by the Agent runtime.
    """

    __tablename__ = "memory_entries"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, server_default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="user")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="1")
    source_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_memory_entries_user_scope_project", "user_id", "scope", "project_name"),
        Index("ix_memory_entries_user_confirmed", "user_id", "confirmed", "updated_at"),
    )


class MemoryCandidate(TimestampMixin, UserOwnedMixin, Base):
    """An Agent-proposed memory awaiting explicit user confirmation."""

    __tablename__ = "memory_candidates"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    scope: Mapped[str] = mapped_column(String(16), nullable=False)
    project_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    category: Mapped[str] = mapped_column(String(32), nullable=False, server_default="other")
    content: Mapped[str] = mapped_column(Text, nullable=False)
    source: Mapped[str] = mapped_column(String(32), nullable=False, server_default="agent")
    confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="pending")
    source_session_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    source_message_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    metadata_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    __table_args__ = (
        Index("ix_memory_candidates_user_scope_project", "user_id", "scope", "project_name"),
        Index("ix_memory_candidates_user_status", "user_id", "status", "updated_at"),
    )


__all__ = ["MemoryEntry", "MemoryCandidate"]

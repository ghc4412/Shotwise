"""Durable publishing account and encrypted credential model."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin


class PublishingAccount(TimestampMixin, Base):
    __tablename__ = "publishing_accounts"
    __table_args__ = (
        UniqueConstraint("user_id", "platform", "platform_account_id", name="uq_publishing_account_identity"),
        Index("ix_publishing_accounts_user_platform", "user_id", "platform"),
        Index("ix_publishing_accounts_status", "user_id", "status"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    user_id: Mapped[str] = mapped_column(
        String(128), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    platform: Mapped[str] = mapped_column(String(64), nullable=False)
    platform_account_id: Mapped[str] = mapped_column(String(256), nullable=False)
    account_name: Mapped[str] = mapped_column(String(256), nullable=False)
    avatar_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_access_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    encrypted_refresh_token: Mapped[str | None] = mapped_column(Text, nullable=True)
    token_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    scopes_json: Mapped[str] = mapped_column(Text, nullable=False, server_default="[]")
    encryption_key_version: Mapped[str] = mapped_column(String(16), nullable=False, server_default="v1")
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="active")
    last_refresh_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)


__all__ = ["PublishingAccount"]

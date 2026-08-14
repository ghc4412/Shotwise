"""Agent session ORM model."""

from __future__ import annotations

from sqlalchemy import Index, String
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import Base, TimestampMixin, UserOwnedMixin


class AgentSession(TimestampMixin, UserOwnedMixin, Base):
    """逻辑会话（共享时间线）：一个会话可交替由 Claude / OpenAI Agents 续写。

    ``sdk_session_id`` 是会话创建时所在 SDK 生成的会话 id，兼作对外逻辑 id，
    一旦创建不再变化。``sdk_type`` 记录当前活跃的 Agent 类型；OpenAI Agents SDK
    的会话历史由 SQLiteSession 按 ``sdk_session_id`` 持久化（无需额外列），切到
    Claude 时其 resume id 存入 ``claude_resume_id`` 供日后续接。
    """

    __tablename__ = "agent_sessions"

    id: Mapped[str] = mapped_column(String, primary_key=True)
    sdk_session_id: Mapped[str] = mapped_column(String, unique=True)
    project_name: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, server_default="")
    status: Mapped[str] = mapped_column(String, server_default="idle")
    # 当前活跃 Agent SDK 类型："claude" | "openai"
    sdk_type: Mapped[str] = mapped_column(String(16), server_default="claude", nullable=False)
    # Claude SDK 会话 id（resume id）；sdk_type=openai 且该会话曾切到 claude 时记录
    claude_resume_id: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        Index("idx_agent_sessions_project", "project_name", "updated_at"),
        Index("idx_agent_sessions_status", "status"),
        Index("idx_agent_sessions_sdk_type", "sdk_type"),
    )

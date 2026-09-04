"""Agent 凭证 ORM。

每个 user 每种 sdk_type 至多一条 is_active=True，由 partial unique index 保证
(与 ProviderCredential 同模式)。
"""

from __future__ import annotations

from sqlalchemy import JSON, Boolean, Index, String, Text, text
from sqlalchemy.orm import Mapped, mapped_column

from lib.db.base import DEFAULT_USER_ID, Base, TimestampMixin


class AgentAnthropicCredential(TimestampMixin, Base):
    """用户保存的多套 Agent 凭证；可在 UI 上一键切换 active。

    ``sdk_type`` 区分 Agent SDK 接入方式：``claude``（Anthropic 协议端点，
    Claude Agent SDK）或 ``openai``（OpenAI 协议端点，OpenAI Agents SDK）。
    active 在 (user, sdk_type) 维度互斥——两种 Agent 可以各自激活一条凭证。
    """

    __tablename__ = "agent_anthropic_credentials"
    __table_args__ = (
        Index("ix_agent_credential_user", "user_id"),
        # 每个 user 每种 sdk_type 至多一条 is_active=True
        Index(
            "uq_agent_credential_one_active_per_user_sdk",
            "user_id",
            "sdk_type",
            unique=True,
            sqlite_where=text("is_active = 1"),
            postgresql_where=text("is_active"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String(64), nullable=False, default=DEFAULT_USER_ID)
    sdk_type: Mapped[str] = mapped_column(String(16), nullable=False, default="claude")  # "claude" | "openai"
    protocol: Mapped[str] = mapped_column(
        String(32), nullable=False, default="chat_completions", server_default="chat_completions"
    )
    preset_id: Mapped[str] = mapped_column(String(64), nullable=False)  # "deepseek" | "__custom__" | ...
    display_name: Mapped[str] = mapped_column(String(128), nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[str] = mapped_column(Text, nullable=False)  # 明文，读出 API mask_secret 脱敏
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    haiku_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sonnet_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    opus_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    subagent_model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    # 模型映射表（菜单显示名 → 实际请求模型 → 上下文窗口）；JSON 数组，条目可含
    # menu_name / request_model / context_window(可空)。仅供智能体配置界面读写。
    model_map: Mapped[list | None] = mapped_column(JSON, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

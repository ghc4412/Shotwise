"""Agent runtime data models."""

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel

SessionStatus = Literal["idle", "running", "completed", "error", "interrupted", "closed"]


@dataclass(frozen=True, slots=True)
class SubscriptionReady:
    """会话消息流的首个事件：订阅已原子建立的屏障标记。

    消费方消费到该事件后，可确信其后的直播广播无缝隙——entry 流以此为界
    先补库读存量条目，再消费直播消息，重复由 seq 门槛过滤（身份比对）。
    """


@dataclass(frozen=True, slots=True)
class LiveMessage:
    """会话消息流的直播事件：订阅屏障之后逐条广播的消息。"""

    message: dict[str, Any]


@dataclass(frozen=True, slots=True)
class Heartbeat:
    """会话消息流的心跳事件：idle_timeout 内无消息时产出。

    消费方在其上执行存活自检（SSE 查断线、同步收集方查 deadline/会话状态），
    保证空闲期也有确定性的醒来时机（见 ADR-0005）。
    """


SessionStreamEvent = SubscriptionReady | LiveMessage | Heartbeat
"""``SessionManager.stream_messages`` 产出的语义化事件。

序列协议：SubscriptionReady（恰好一次、必为首个）→ LiveMessage / Heartbeat 交错；
订阅队列溢出以流结束表达，流结束即重连信号，无专门事件。
"""


class SessionMeta(BaseModel):
    """Session metadata stored in database."""

    id: str  # 对外暴露，填充 sdk_session_id 值
    project_name: str
    title: str = ""
    status: SessionStatus = "idle"
    # 当前活跃 Agent SDK 类型："claude" | "openai"
    sdk_type: str = "claude"
    # Claude 会话的 SDK resume id（当 sdk_session_id 不是 Claude resume id 时落库）
    claude_resume_id: str | None = None
    created_at: datetime
    updated_at: datetime

    def resolve_sdk_session_id(self, sdk_type: str) -> str | None:
        """按目标 sdk_type 解析续接用的 SDK 会话 id。

        - claude：优先读 ``claude_resume_id``；否则当前就是 claude 会话时用
          ``sdk_session_id``（即 Claude resume id）；否则返回 None（Claude 新建）。
        - openai：OpenAI Agents SDK 的会话历史由 SQLiteSession 按
          ``sdk_session_id`` 持久化，续接直接用对外 id。
        """
        if sdk_type == "claude":
            if self.claude_resume_id:
                return self.claude_resume_id
            return self.id if self.sdk_type == "claude" else None
        if sdk_type == "openai":
            return self.id
        return None

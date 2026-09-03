"""OpenAI Agents SDK 的 StreamEvent → 现有 Agent 运行时消息协议翻译器。

把 ``agents`` 的 ``RunResultStreaming.stream_events()`` 产出的事件翻译成
SessionActor / entry_pipeline / 前端渲染共用的 Anthropic 风格消息 dict
（``type`` = system / stream_event / assistant / user）。Claude 与 OpenAI
两条 SDK 通道复用同一套事件日志、draft 预览、SSE 流与前端渲染。

翻译要点：
- 首条输出携带 ``session_id``（对外 sdk_session_id），供 SessionManager 的
  sdk_session_id 捕获机制（新会话建 DB 记录）。
- ``raw_response_event`` 的文本 delta → text 块的 message_start /
  content_block_delta；``response.created`` 建立消息身份（response.id）。
- ``run_item_stream_event`` 的 ``message_output_item`` → 完整 assistant 消息；
  ``tool_call_item`` → tool_use 块；``tool_call_output_item`` → user 消息的
  tool_result 块（按 call_id 关联）。
- ``result`` 消息（session_status / model / usage）由 client 在流结束后构造。

本模块无 I/O、无外部依赖（除 ``agents`` 的类型），纯函数可测。
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)


class OpenAIAgentsTranslator:
    """有状态翻译器：消费一次 run 的完整事件流，产出消息 dict 列表。"""

    def __init__(self, *, session_id: str, model: str) -> None:
        self.session_id = session_id
        self.model = model
        self._emitted_session_id = False
        # 当前 assistant 消息累积态（draft 协议：单 message_id 多 block）
        self._message_id: str | None = None
        self._blocks: dict[int, dict[str, Any]] = {}
        self._text_buf: list[str] = []
        # tool_use 块累积：call_id → (block_index, name, input)
        self._tool_uses: dict[str, dict[str, Any]] = {}
        self._has_assistant_output = False

    @property
    def has_assistant_output(self) -> bool:
        return self._has_assistant_output

    def flush_partial_assistant(self) -> dict[str, Any] | None:
        """把已收到但尚未收到 ``message_output_item`` 的文本定型。

        流式连接可能在文本 delta 之后、权威消息条目之前断开。调用方应只在
        失败收尾路径调用此方法；工具调用的半成品不在这里伪造成完整 assistant
        消息，只有已经可见的文本会被保留下来。
        """
        text = "".join(self._text_buf)
        if not text.strip():
            return None
        message_id = self._message_id or None
        self._message_id = None
        self._blocks = {}
        self._text_buf = []
        return {
            "type": "assistant",
            "message_id": message_id,
            "content": [{"type": "text", "text": text}],
        }

    # ── 事件入口 ────────────────────────────────────────────────────

    def feed(self, event: Any) -> list[dict[str, Any]]:
        """处理一个 StreamEvent，返回 0..N 条消息 dict。"""
        event_type = getattr(event, "type", None)
        if event_type == "raw_response_event":
            return self._on_raw_event(getattr(event, "data", None))
        if event_type == "run_item_stream_event":
            return self._on_run_item(getattr(event, "item", None))
        # agent_updated_stream_event 及其余事件不翻译
        return []

    # ── raw response 事件：文本流 ───────────────────────────────────

    def _on_raw_event(self, data: Any) -> list[dict[str, Any]]:
        if data is None:
            return []
        data_type = getattr(data, "type", None)

        messages: list[dict[str, Any]] = []
        self._emit_session_id(messages)

        if data_type == "response.created":
            response = getattr(data, "response", None)
            response_id = getattr(response, "id", None)
            if response_id:
                self._begin_text_message(str(response_id))
                messages.append(self._message_start(str(response_id)))
                messages.append(self._content_block_start(0, {"type": "text", "text": ""}))
            return messages

        if data_type == "response.output_text.delta":
            delta = getattr(data, "delta", None)
            if isinstance(delta, str) and delta:
                if self._message_id is None:
                    self._begin_text_message("")
                    messages.append(self._message_start(""))
                    messages.append(self._content_block_start(0, {"type": "text", "text": ""}))
                self._text_buf.append(delta)
                self._has_assistant_output = True
                messages.append(self._content_block_delta(0, "text_delta", {"text": delta}))
            return messages

        return messages

    # ── run item 事件：工具调用 / 完整消息 ─────────────────────────

    def _on_run_item(self, item: Any) -> list[dict[str, Any]]:
        if item is None:
            return []
        item_type = getattr(item, "type", None)
        messages: list[dict[str, Any]] = []

        if item_type == "tool_call_item":
            self._emit_session_id(messages)
            messages.extend(self._on_tool_call(item))
        elif item_type == "tool_call_output_item":
            self._emit_session_id(messages)
            messages.extend(self._on_tool_output(item))
        elif item_type == "message_output_item":
            self._emit_session_id(messages)
            messages.extend(self._on_message_output(item))
        elif item_type == "reasoning_item":
            self._emit_session_id(messages)
            # reasoning 只做流式预览不落库；draft 会在 assistant 完成时清理
            messages.extend(self._on_reasoning(item))
        return messages

    def _on_tool_call(self, item: Any) -> list[dict[str, Any]]:
        raw = getattr(item, "raw_item", None)
        name = getattr(item, "tool_name", None) or getattr(raw, "name", None) or "tool"
        call_id = str(getattr(item, "call_id", None) or "")
        arguments_raw = getattr(raw, "arguments", None)
        arguments: dict[str, Any] = {}
        if isinstance(arguments_raw, str) and arguments_raw:
            try:
                parsed = json.loads(arguments_raw)
                if isinstance(parsed, dict):
                    arguments = parsed
            except json.JSONDecodeError:
                arguments = {"_raw": arguments_raw}
        index = self._next_block_index()
        self._tool_uses[call_id] = {"index": index, "name": str(name), "input": arguments}
        return [
            self._content_block_start(index, {"type": "tool_use", "id": call_id, "name": str(name), "input": arguments})
        ]

    def _on_tool_output(self, item: Any) -> list[dict[str, Any]]:
        call_id = str(getattr(item, "call_id", None) or "")
        output = getattr(item, "output", None)
        content_text = _stringify(output) if output is not None else ""
        return [
            {
                "type": "user",
                "content": [{"type": "tool_result", "tool_use_id": call_id, "content": content_text}],
            }
        ]

    def _on_message_output(self, item: Any) -> list[dict[str, Any]]:
        from agents import ItemHelpers

        try:
            text = ItemHelpers.text_message_output(item)
        except Exception:
            text = ""
        message_id = None
        raw = getattr(item, "raw_item", None)
        raw_id = getattr(raw, "id", None)
        if raw_id:
            message_id = str(raw_id)
        elif self._message_id:
            message_id = self._message_id
        self._message_id = None
        self._blocks = {}
        self._text_buf = []
        if text.strip():
            self._has_assistant_output = True
        return [
            {
                "type": "assistant",
                "message_id": message_id,
                "content": [{"type": "text", "text": text}],
            }
        ]

    def _on_reasoning(self, item: Any) -> list[dict[str, Any]]:
        raw = getattr(item, "raw_item", None)
        summary = getattr(raw, "summary", None)
        if not isinstance(summary, list):
            return []
        thinking = "\n".join(_stringify(part) for part in summary if part)
        if not thinking:
            return []
        index = self._next_block_index() if self._blocks else 0
        return [self._content_block_delta(index, "thinking_delta", {"thinking": thinking})]

    # ── 内部 helpers ───────────────────────────────────────────────

    def _emit_session_id(self, messages: list[dict[str, Any]]) -> None:
        if self._emitted_session_id:
            return
        self._emitted_session_id = True
        messages.append({"type": "system", "session_id": self.session_id, "subtype": "sdk_session_id"})

    def _begin_text_message(self, message_id: str) -> None:
        self._message_id = message_id
        self._blocks = {}
        self._text_buf = []

    def _next_block_index(self) -> int:
        if not self._blocks:
            return 0
        return max(self._blocks.keys()) + 1

    def _message_start(self, message_id: str) -> dict[str, Any]:
        return {"type": "stream_event", "event": {"type": "message_start", "message": {"id": message_id}}}

    def _content_block_start(self, index: int, block: dict[str, Any]) -> dict[str, Any]:
        self._blocks[index] = block
        return {
            "type": "stream_event",
            "event": {"type": "content_block_start", "index": index, "content_block": block},
        }

    def _content_block_delta(self, index: int, delta_type: str, delta: dict[str, Any]) -> dict[str, Any]:
        block = self._blocks.get(index)
        if block is not None and delta_type == "text_delta":
            block["text"] = f"{block.get('text', '')}{delta.get('text', '')}"
        elif block is not None and delta_type == "thinking_delta":
            block["thinking"] = f"{block.get('thinking', '')}{delta.get('thinking', '')}"
        return {
            "type": "stream_event",
            "event": {"type": "content_block_delta", "index": index, "delta": {"type": delta_type, **delta}},
        }


def _stringify(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float, bool)):
        return str(value)
    try:
        from pydantic import BaseModel

        if isinstance(value, BaseModel):
            return value.model_dump_json()
    except Exception:  # pragma: no cover
        pass
    try:
        return json.dumps(value, ensure_ascii=False, default=str)
    except (TypeError, ValueError):  # pragma: no cover
        return str(value)

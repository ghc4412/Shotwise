"""OpenAIAgentsTranslator 单元测试：Agents SDK 事件 → 现有消息协议。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from server.agent_runtime.openai_agents_translator import OpenAIAgentsTranslator

pytestmark = pytest.mark.unit


@dataclass
class FakeEvent:
    type: str
    data: Any = None
    item: Any = None


class _D:
    """faux data with attribute access"""

    def __init__(self, **fields: Any) -> None:
        for key, value in fields.items():
            setattr(self, key, value)


def test_first_event_emits_session_id_once() -> None:
    tr = OpenAIAgentsTranslator(session_id="sess-1", model="gpt-x")
    msgs = tr.feed(FakeEvent("raw_response_event", data=_D(type="response.created", response=_D(id="resp-1"))))
    # 首条包含 session_id 系统消息 + message_start + content_block_start
    assert msgs[0]["type"] == "system"
    assert msgs[0]["session_id"] == "sess-1"
    # 后续事件不再重复 session_id
    out_item = _D(type="tool_call_output_item", call_id="c1", output="ok")
    later = tr.feed(FakeEvent("run_item_stream_event", item=out_item))
    assert all(m.get("type") != "system" for m in later)


def test_text_streaming_and_message_completion() -> None:
    tr = OpenAIAgentsTranslator(session_id="sess-1", model="gpt-x")
    created = tr.feed(FakeEvent("raw_response_event", data=_D(type="response.created", response=_D(id="resp-1"))))
    assert created[1]["event"]["type"] == "message_start"
    assert created[1]["event"]["message"]["id"] == "resp-1"
    assert created[2]["event"]["content_block"]["type"] == "text"

    delta = tr.feed(FakeEvent("raw_response_event", data=_D(type="response.output_text.delta", delta="你好")))
    assert delta[0]["event"]["type"] == "content_block_delta"
    assert delta[0]["event"]["delta"] == {"type": "text_delta", "text": "你好"}

    # message_output_item → 完整 assistant 消息
    item = _D(type="message_output_item", raw_item=_D(id="resp-1"))
    # ItemHelpers.text_message_output 依赖真实 MessageOutputItem，这里直接测结构分支：
    # 用 raw_item 带 text 字段，绕过 ItemHelpers
    completed = tr.feed(FakeEvent("run_item_stream_event", item=item))
    # text_message_output 对 fake item 会抛异常 → 文本为空，但结构仍产出 assistant 消息
    assert len(completed) == 1
    assert completed[0]["type"] == "assistant"
    assert completed[0]["message_id"] == "resp-1"


def test_tool_call_and_output() -> None:
    tr = OpenAIAgentsTranslator(session_id="sess-1", model="gpt-x")
    tr.feed(FakeEvent("raw_response_event", data=_D(type="response.created", response=_D(id="resp-1"))))

    call_item = _D(
        type="tool_call_item", tool_name="generate_assets", call_id="call-1", raw_item=_D(arguments='{"count": 3}')
    )
    started = tr.feed(FakeEvent("run_item_stream_event", item=call_item))
    block = started[-1]["event"]["content_block"]
    assert block["type"] == "tool_use"
    assert block["name"] == "generate_assets"
    assert block["input"] == {"count": 3}

    out_item = _D(type="tool_call_output_item", call_id="call-1", output="done")
    completed = tr.feed(FakeEvent("run_item_stream_event", item=out_item))
    assert completed[0]["type"] == "user"
    assert completed[0]["content"][0]["type"] == "tool_result"
    assert completed[0]["content"][0]["tool_use_id"] == "call-1"
    assert completed[0]["content"][0]["content"] == "done"


def test_tool_call_with_non_json_arguments() -> None:
    tr = OpenAIAgentsTranslator(session_id="sess-1", model="gpt-x")
    tr.feed(FakeEvent("raw_response_event", data=_D(type="response.created", response=_D(id="resp-1"))))
    call_item = _D(type="tool_call_item", tool_name="t", call_id="c1", raw_item=_D(arguments="not-json"))
    started = tr.feed(FakeEvent("run_item_stream_event", item=call_item))
    assert started[-1]["event"]["content_block"]["input"] == {"_raw": "not-json"}


def test_unknown_events_ignored() -> None:
    tr = OpenAIAgentsTranslator(session_id="sess-1", model="gpt-x")
    assert tr.feed(FakeEvent("agent_updated_stream_event", data=_D())) == []
    assert tr.feed(FakeEvent("run_item_stream_event", item=None)) == []
    assert tr.feed(FakeEvent("raw_response_event", data=None)) == []

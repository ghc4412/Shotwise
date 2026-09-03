"""OpenAI Agents client stream termination regression tests."""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from server.agent_runtime.openai_agents_client import _EOS, OpenAIAgentsSessionClient

pytestmark = pytest.mark.unit


class _FakeResult:
    def __init__(self, events: list[Any]) -> None:
        self.events = events

    async def stream_events(self):
        for event in self.events:
            yield event


class _FailingResult:
    def __init__(self, error: Exception) -> None:
        self.error = error

    async def stream_events(self):
        raise self.error
        yield  # pragma: no cover - makes this an async generator


class _FakeTranslator:
    def __init__(
        self,
        *,
        has_assistant_output: bool,
        messages: list[dict[str, Any]] | None = None,
        partial_assistant: dict[str, Any] | None = None,
    ) -> None:
        self.has_assistant_output = has_assistant_output
        self.messages = messages or []
        self.partial_assistant = partial_assistant

    def feed(self, _event: Any) -> list[dict[str, Any]]:
        return self.messages

    def flush_partial_assistant(self) -> dict[str, Any] | None:
        return self.partial_assistant


def _client() -> OpenAIAgentsSessionClient:
    return OpenAIAgentsSessionClient(
        provider=None,
        model="compatible-model",
        system_prompt="",
        session=None,
        tools=[],
        max_turns=None,
    )


@pytest.mark.asyncio
async def test_empty_provider_stream_is_reported_as_error() -> None:
    client = _client()
    client._outbox = asyncio.Queue()
    client._result = _FakeResult(events=[object()])
    client._translator = _FakeTranslator(has_assistant_output=False)

    await client._drain_stream()

    result = await client._outbox.get()
    assert result == {
        "type": "result",
        "session_status": "error",
        "model": "compatible-model",
        "usage": {},
        "error": "provider_empty_response",
    }
    assert await client._outbox.get() is _EOS


@pytest.mark.asyncio
async def test_provider_stream_with_assistant_text_is_completed() -> None:
    client = _client()
    client._outbox = asyncio.Queue()
    client._result = _FakeResult(events=[object()])
    client._translator = _FakeTranslator(
        has_assistant_output=True,
        messages=[{"type": "assistant", "content": [{"type": "text", "text": "ok"}]}],
    )

    await client._drain_stream()

    assistant = await client._outbox.get()
    assert assistant["type"] == "assistant"
    result = await client._outbox.get()
    assert result["session_status"] == "completed"
    assert await client._outbox.get() is _EOS


@pytest.mark.asyncio
async def test_interrupted_provider_stream_preserves_partial_assistant_text() -> None:
    client = _client()
    client._outbox = asyncio.Queue()
    client._result = _FailingResult(Exception("peer closed connection without sending complete message body"))
    client._translator = _FakeTranslator(
        has_assistant_output=True,
        partial_assistant={
            "type": "assistant",
            "message_id": "resp-1",
            "content": [{"type": "text", "text": "已经收到的内容"}],
        },
    )

    await client._drain_stream()

    assistant = await client._outbox.get()
    assert assistant["type"] == "assistant"
    assert assistant["content"][0]["text"] == "已经收到的内容"
    result = await client._outbox.get()
    assert result["session_status"] == "error"
    assert result["error"] == "provider_stream_interrupted"
    assert "complete message body" in result["error_detail"]
    assert await client._outbox.get() is _EOS


@pytest.mark.asyncio
async def test_interrupted_empty_provider_stream_does_not_emit_empty_assistant() -> None:
    client = _client()
    client._outbox = asyncio.Queue()
    client._result = _FailingResult(Exception("connection reset"))
    client._translator = _FakeTranslator(has_assistant_output=False)

    await client._drain_stream()

    result = await client._outbox.get()
    assert result["type"] == "result"
    assert result["session_status"] == "error"
    assert result["error"] == "provider_stream_interrupted"
    assert await client._outbox.get() is _EOS

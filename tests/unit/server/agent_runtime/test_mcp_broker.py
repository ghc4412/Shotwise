"""Tests for the first-stage MCP tool broker public seam."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any

import pytest

from server.agent_runtime.mcp_broker import (
    MCPAuditEvent,
    MCPExecutionRequest,
    MCPToolBroker,
    MCPToolDefinition,
    ToolOperation,
)


class RecordingAdapter:
    def __init__(self, *, result: Mapping[str, Any] | None = None, error: Exception | None = None) -> None:
        self.result = dict(result or {"items": []})
        self.error = error
        self.requests: list[MCPExecutionRequest] = []
        self.cancelled_request_ids: list[str] = []

    async def execute(self, request: MCPExecutionRequest) -> Mapping[str, Any]:
        self.requests.append(request)
        if self.error is not None:
            raise self.error
        return self.result

    async def cancel(self, request_id: str) -> None:
        self.cancelled_request_ids.append(request_id)


class SleepingAdapter(RecordingAdapter):
    async def execute(self, request: MCPExecutionRequest) -> Mapping[str, Any]:
        self.requests.append(request)
        await asyncio.sleep(10)
        return self.result


class RecordingAuditSink:
    def __init__(self) -> None:
        self.events: list[MCPAuditEvent] = []

    async def record(self, event: MCPAuditEvent) -> None:
        self.events.append(event)


def _read_tool(*, timeout_seconds: float = 1.0) -> MCPToolDefinition:
    return MCPToolDefinition(
        name="knowledge.search",
        adapter_id="local",
        operation=ToolOperation.READ_ONLY,
        input_schema={
            "type": "object",
            "required": ["query"],
            "properties": {"query": {"type": "string"}},
            "additionalProperties": False,
        },
        timeout_seconds=timeout_seconds,
    )


def _broker(
    adapter: RecordingAdapter,
    audit_sink: RecordingAuditSink,
    tool: MCPToolDefinition | None = None,
) -> MCPToolBroker:
    return MCPToolBroker(
        tools=[tool or _read_tool()],
        adapters={"local": adapter},
        allowed_tools={"knowledge.search"},
        audit_sink=audit_sink,
    )


@pytest.mark.unit
async def test_execute_allows_allowlisted_read_only_tool_and_preserves_trace_context() -> None:
    adapter = RecordingAdapter(result={"items": [{"id": "note-1"}]})
    audit_sink = RecordingAuditSink()

    result = await _broker(adapter, audit_sink).execute(
        "knowledge.search",
        {"query": "story beats"},
        request_id="request-123",
        trace_id="trace-123",
    )

    assert result.ok is True
    assert result.payload == {"items": [{"id": "note-1"}]}
    assert result.error is None
    assert result.request_id == "request-123"
    assert result.trace_id == "trace-123"
    assert adapter.requests == [
        MCPExecutionRequest(
            tool_name="knowledge.search",
            arguments={"query": "story beats"},
            request_id="request-123",
            trace_id="trace-123",
        )
    ]
    assert [(event.outcome, event.request_id, event.trace_id) for event in audit_sink.events] == [
        ("succeeded", "request-123", "trace-123")
    ]


@pytest.mark.unit
async def test_execute_rejects_write_tool_even_when_allowlisted() -> None:
    adapter = RecordingAdapter()
    audit_sink = RecordingAuditSink()
    write_tool = MCPToolDefinition(
        name="project.patch",
        adapter_id="local",
        operation=ToolOperation.WRITE,
        input_schema={"type": "object"},
    )
    broker = MCPToolBroker(
        tools=[write_tool],
        adapters={"local": adapter},
        allowed_tools={"project.patch"},
        audit_sink=audit_sink,
    )

    result = await broker.execute("project.patch", {})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "operation_not_supported"
    assert adapter.requests == []
    assert audit_sink.events[-1].outcome == "rejected"


@pytest.mark.unit
async def test_execute_rejects_arguments_that_do_not_match_tool_schema() -> None:
    adapter = RecordingAdapter()
    audit_sink = RecordingAuditSink()

    result = await _broker(adapter, audit_sink).execute("knowledge.search", {"query": 42})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "invalid_arguments"
    assert result.error.details == {"path": "$.query", "reason": "expected string"}
    assert adapter.requests == []
    assert audit_sink.events[-1].outcome == "rejected"


@pytest.mark.unit
async def test_execute_returns_normalized_timeout_error() -> None:
    adapter = SleepingAdapter()
    audit_sink = RecordingAuditSink()

    result = await _broker(adapter, audit_sink, _read_tool(timeout_seconds=0.001)).execute(
        "knowledge.search", {"query": "slow"}
    )

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "tool_timeout"
    assert result.error.details == {"timeout_seconds": 0.001}
    assert audit_sink.events[-1].outcome == "timed_out"


@pytest.mark.unit
async def test_execute_normalizes_adapter_failures_without_exposing_exception_details() -> None:
    adapter = RecordingAdapter(error=RuntimeError("provider secret: abc"))
    audit_sink = RecordingAuditSink()

    result = await _broker(adapter, audit_sink).execute("knowledge.search", {"query": "failure"})

    assert result.ok is False
    assert result.error is not None
    assert result.error.code == "adapter_execution_failed"
    assert result.error.message == "The MCP tool could not complete the request."
    assert result.error.details == {}
    assert audit_sink.events[-1].outcome == "failed"


@pytest.mark.unit
async def test_execute_cancels_adapter_when_caller_cancels() -> None:
    adapter = SleepingAdapter()
    audit_sink = RecordingAuditSink()
    broker = _broker(adapter, audit_sink)

    task = asyncio.create_task(broker.execute("knowledge.search", {"query": "cancel"}, request_id="cancel-request"))
    await asyncio.sleep(0)
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert adapter.cancelled_request_ids == ["cancel-request"]
    assert audit_sink.events[-1].outcome == "cancelled"

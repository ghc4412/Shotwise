"""Tests for the first-stage remote MCP JSON-RPC adapter."""

from __future__ import annotations

import asyncio
import inspect
import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
import pytest

from server.agent_runtime.mcp_broker import MCPExecutionRequest
from server.agent_runtime.remote_mcp_runtime import RemoteMCPManifest, _build_sdk_tools
from server.agent_runtime.remote_mcp_transport import (
    RemoteMCPRuntime,
    RemoteMCPTransport,
    RemoteMCPTransportError,
)


def _transport(
    handler: Callable[[httpx.Request], httpx.Response | Awaitable[httpx.Response]],
    *,
    allowed_tools: set[str] | None = None,
    **kwargs: Any,
) -> RemoteMCPTransport:
    async def dispatch(request: httpx.Request) -> httpx.Response:
        result = handler(request)
        if isinstance(result, httpx.Response):
            return result
        return await result

    return RemoteMCPTransport(
        "https://mcp.example.test/rpc",
        allowed_tools=allowed_tools or {"knowledge.search"},
        http_transport=httpx.MockTransport(dispatch),
        **kwargs,
    )


def _rpc_result(request: httpx.Request, result: Any) -> httpx.Response:
    body = json.loads(request.content)
    return httpx.Response(
        200,
        json={"jsonrpc": "2.0", "id": body.get("id"), "result": result},
        request=request,
    )


@pytest.mark.unit
async def test_initialize_tools_list_and_call_use_minimal_json_rpc_protocol() -> None:
    requests: list[dict[str, Any]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body["method"] == "initialize":
            return _rpc_result(
                request,
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {"tools": {}},
                    "serverInfo": {"name": "knowledge", "version": "1"},
                },
            )
        if body["method"] == "notifications/initialized":
            return httpx.Response(202, request=request)
        if body["method"] == "tools/list":
            return _rpc_result(request, {"tools": [{"name": "knowledge.search", "inputSchema": {}}]})
        if body["method"] == "tools/call":
            return _rpc_result(request, {"content": [{"type": "text", "text": "ok"}]})
        raise AssertionError(body)

    adapter = _transport(handler)

    initialized = await adapter.initialize()
    listed = await adapter.list_tools()
    result = await adapter.execute(_request("knowledge.search", {"query": "beats"}, request_id="call-1"))
    await adapter.aclose()

    assert initialized["protocolVersion"] == "2025-06-18"
    assert listed == ({"name": "knowledge.search", "inputSchema": {}},)
    assert result == {"content": [{"type": "text", "text": "ok"}]}
    assert [request["method"] for request in requests] == [
        "initialize",
        "notifications/initialized",
        "tools/list",
        "tools/call",
    ]
    assert requests[-1]["id"] == "call-1"
    assert requests[-1]["params"] == {"name": "knowledge.search", "arguments": {"query": "beats"}}


@pytest.mark.unit
async def test_list_tools_filters_remote_catalog_to_read_only_allowlist() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        return _rpc_result(
            request,
            {
                "tools": [
                    {"name": "knowledge.search", "description": "read"},
                    {"name": "project.patch", "description": "write"},
                ]
            },
        )

    adapter = _transport(handler, allowed_tools={"knowledge.search"})

    assert await adapter.list_tools() == ({"name": "knowledge.search", "description": "read"},)
    with pytest.raises(RemoteMCPTransportError) as error:
        await adapter.execute(_request("project.patch", {}, request_id="blocked"))

    assert error.value.code == "tool_not_allowed"
    assert error.value.details == {}


@pytest.mark.unit
async def test_remote_json_rpc_errors_are_mapped_without_remote_details() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "error": {"code": -32001, "message": "secret database password", "data": {"token": "abc"}},
            },
            request=request,
        )

    adapter = _transport(handler)

    with pytest.raises(RemoteMCPTransportError) as error:
        await adapter.execute(_request("knowledge.search", {"query": "x"}, request_id="call-2"))

    assert error.value.code == "remote_tool_failed"
    assert error.value.message == "The remote MCP tool failed."
    assert error.value.details == {}
    assert "password" not in str(error.value)
    assert "abc" not in str(error.value)


@pytest.mark.unit
async def test_tools_call_is_error_result_uses_the_same_stable_error_message() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        return _rpc_result(request, {"isError": True, "content": [{"type": "text", "text": "secret"}]})

    with pytest.raises(RemoteMCPTransportError) as error:
        await _transport(handler).execute(_request("knowledge.search", {}, request_id="call-3"))

    assert error.value.code == "remote_tool_failed"
    assert error.value.message == "The remote MCP tool failed."
    assert error.value.details == {}
    assert "secret" not in str(error.value)


@pytest.mark.unit
async def test_build_broker_discovers_allowlisted_remote_tools_as_read_only_definitions() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        if body["method"] == "tools/list":
            return _rpc_result(
                request,
                {
                    "tools": [
                        {
                            "name": "knowledge.search",
                            "inputSchema": {
                                "type": "object",
                                "required": ["query"],
                                "properties": {"query": {"type": "string"}},
                            },
                        },
                        {"name": "project.patch", "inputSchema": {"type": "object"}},
                    ]
                },
            )
        return _rpc_result(request, {"content": [{"type": "text", "text": "ok"}]})

    transport = _transport(handler)
    broker = await RemoteMCPRuntime(transport).build_broker()

    allowed = await broker.execute("knowledge.search", {"query": "beats"})
    blocked = await broker.execute("project.patch", {})

    assert allowed.ok is True
    assert blocked.ok is False
    assert blocked.error is not None
    assert blocked.error.code == "tool_not_allowed"

    sdk_tools = _build_sdk_tools(broker)
    assert len(sdk_tools) == 1
    assert list(inspect.signature(sdk_tools[0].handler).parameters) == ["args"]
    assert await sdk_tools[0].handler({"query": "beats"}) == {"content": [{"type": "text", "text": "ok"}]}


@pytest.mark.unit
async def test_manifest_cleanup_attempts_every_transport_and_is_idempotent() -> None:
    calls: list[str] = []

    class _Transport:
        def __init__(self, name: str, *, fail: bool = False) -> None:
            self.name = name
            self.fail = fail

        async def aclose(self) -> None:
            calls.append(self.name)
            if self.fail:
                raise RuntimeError(self.name)

    manifest = RemoteMCPManifest(
        servers={},
        allowed_tools=(),
        _transports=[_Transport("first", fail=True), _Transport("second")],  # type: ignore[list-item]
    )

    with pytest.raises(RuntimeError, match="first"):
        await manifest.aclose()
    await manifest.aclose()

    assert calls == ["first", "second"]


@pytest.mark.unit
async def test_build_broker_rejects_remote_tools_with_non_mapping_input_schema() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        return _rpc_result(request, {"tools": [{"name": "knowledge.search", "inputSchema": []}]})

    with pytest.raises(RemoteMCPTransportError) as error:
        await RemoteMCPRuntime(_transport(handler)).build_broker()

    assert error.value.code == "protocol_error"
    assert error.value.message == "The remote MCP server returned an invalid tool definition."
    assert error.value.details == {}


@pytest.mark.unit
async def test_request_and_response_size_limits_are_enforced() -> None:
    adapter = _transport(
        lambda request: httpx.Response(200, content=b'{"jsonrpc":"2.0"}', request=request),
        max_request_bytes=100,
    )

    with pytest.raises(RemoteMCPTransportError) as request_error:
        await adapter.execute(_request("knowledge.search", {"query": "x" * 200}, request_id="large"))

    assert request_error.value.code == "request_too_large"

    response_adapter = _transport(
        lambda request: httpx.Response(200, content=b"x" * 101, request=request),
        max_response_bytes=100,
    )
    with pytest.raises(RemoteMCPTransportError) as response_error:
        await response_adapter.initialize()

    assert response_error.value.code == "response_too_large"


@pytest.mark.unit
async def test_timeout_and_cancellation_are_mapped_and_cancel_notification_is_best_effort() -> None:
    requests: list[dict[str, Any]] = []
    request_seen = asyncio.Event()

    async def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if body["method"] == "initialize":
            return _rpc_result(request, {"protocolVersion": "2025-06-18", "capabilities": {}})
        if body["method"] == "notifications/initialized":
            return httpx.Response(200, request=request)
        if body["method"] == "notifications/cancelled":
            return httpx.Response(202, request=request)
        request_seen.set()
        await asyncio.sleep(10)
        return _rpc_result(request, {"content": []})

    adapter = _transport(handler, timeout_seconds=0.01)
    task = asyncio.create_task(adapter.execute(_request("knowledge.search", {}, request_id="cancel-me")))
    await request_seen.wait()

    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    await adapter.cancel("cancel-me")
    assert requests[-1] == {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": "cancel-me", "reason": "cancelled"},
    }


@pytest.mark.unit
async def test_http_failures_and_malformed_responses_are_safe() -> None:
    def http_failure(request: httpx.Request) -> httpx.Response:
        return httpx.Response(502, content=b"upstream secret", request=request)

    with pytest.raises(RemoteMCPTransportError) as http_error:
        await _transport(http_failure).initialize()
    assert http_error.value.code == "remote_unavailable"
    assert http_error.value.details == {}
    assert "secret" not in str(http_error.value)

    malformed = _transport(lambda request: httpx.Response(200, content=b"not-json", request=request))
    with pytest.raises(RemoteMCPTransportError) as protocol_error:
        await malformed.initialize()
    assert protocol_error.value.code == "protocol_error"


def _request(tool_name: str, arguments: dict[str, Any], *, request_id: str) -> MCPExecutionRequest:
    return MCPExecutionRequest(
        tool_name=tool_name,
        arguments=arguments,
        request_id=request_id,
        trace_id="trace-1",
    )

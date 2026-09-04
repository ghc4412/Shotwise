"""Small, read-only HTTP JSON-RPC transport for remote MCP servers.

This module is deliberately independent from :mod:`mcp_broker`: the broker
owns authorization and execution policy, while this adapter owns the wire
protocol and remote I/O.  The adapter also repeats the tool allowlist at its
own seam so a transport cannot be used to bypass the first-stage read-only
boundary when it is wired incorrectly.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4

import httpx

from .mcp_broker import (
    MCPAuditSink,
    MCPExecutionRequest,
    MCPToolAdapter,
    MCPToolBroker,
    MCPToolDefinition,
    ToolOperation,
)

_JSON_RPC_VERSION = "2.0"
_DEFAULT_PROTOCOL_VERSION = "2025-06-18"
_DEFAULT_TIMEOUT_SECONDS = 30.0
_DEFAULT_MAX_REQUEST_BYTES = 64 * 1024
_DEFAULT_MAX_RESPONSE_BYTES = 1024 * 1024
_REMOTE_TOOL_FAILED_CODE = "remote_tool_failed"
_REMOTE_TOOL_FAILED_MESSAGE = "The remote MCP tool failed."
_BLOCKED_HEADERS = frozenset(
    {"accept", "connection", "content-length", "content-type", "host", "mcp-session-id", "transfer-encoding"}
)


class RemoteMCPTransportError(RuntimeError):
    """Safe, stable error raised by the remote adapter.

    Remote response text, JSON-RPC error messages and exception strings are
    intentionally excluded from this public error.  They may contain secrets
    or provider implementation details and are therefore not propagated.
    """

    def __init__(self, code: str, message: str, *, details: Mapping[str, Any] | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = dict(details or {})


@dataclass(frozen=True, slots=True)
class RemoteMCPTransportConfig:
    """Validated limits and protocol identity for one remote endpoint."""

    endpoint: str
    allowed_tools: frozenset[str]
    timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS
    max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES
    max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES
    protocol_version: str = _DEFAULT_PROTOCOL_VERSION
    client_name: str = "shotwise"
    client_version: str = "0.1"

    def __post_init__(self) -> None:
        parsed = urlsplit(self.endpoint)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Remote MCP endpoint must be an absolute HTTP(S) URL.")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("Remote MCP endpoint must not contain credentials or a URL fragment.")
        if not self.protocol_version or not self.client_name or not self.client_version:
            raise ValueError("Remote MCP protocol and client identity values must not be empty.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("Remote MCP timeout_seconds must be finite and greater than zero.")
        if self.max_request_bytes <= 0 or self.max_response_bytes <= 0:
            raise ValueError("Remote MCP message size limits must be greater than zero.")
        if any(not name for name in self.allowed_tools):
            raise ValueError("Remote MCP allowed tool names must be non-empty strings.")


class RemoteMCPTransport(MCPToolAdapter):
    """Execute allowlisted MCP tools over a minimal HTTP JSON-RPC 2.0 seam.

    ``http_client`` is useful when application lifetime owns a shared client.
    ``http_transport`` is useful for isolated tests with ``httpx.MockTransport``.
    The adapter owns only a client that it creates itself; call ``aclose()`` or
    use it as an async context manager in that case.
    """

    def __init__(
        self,
        endpoint: str,
        *,
        allowed_tools: Collection[str],
        headers: Mapping[str, str] | None = None,
        timeout_seconds: float = _DEFAULT_TIMEOUT_SECONDS,
        max_request_bytes: int = _DEFAULT_MAX_REQUEST_BYTES,
        max_response_bytes: int = _DEFAULT_MAX_RESPONSE_BYTES,
        protocol_version: str = _DEFAULT_PROTOCOL_VERSION,
        client_name: str = "shotwise",
        client_version: str = "0.1",
        http_client: httpx.AsyncClient | None = None,
        http_transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        if http_client is not None and http_transport is not None:
            raise ValueError("Provide either http_client or http_transport, not both.")

        normalized_headers = _validate_headers(headers or {})
        self.config = RemoteMCPTransportConfig(
            endpoint=endpoint,
            allowed_tools=frozenset(allowed_tools),
            timeout_seconds=timeout_seconds,
            max_request_bytes=max_request_bytes,
            max_response_bytes=max_response_bytes,
            protocol_version=protocol_version,
            client_name=client_name,
            client_version=client_version,
        )
        self._headers = normalized_headers
        self._client = http_client or httpx.AsyncClient(
            transport=http_transport,
            timeout=timeout_seconds,
            follow_redirects=False,
        )
        self._owns_client = http_client is None
        self._initialize_lock = asyncio.Lock()
        self._initialize_result: Mapping[str, Any] | None = None
        self._session_id: str | None = None
        self._closed = False

    async def initialize(self) -> Mapping[str, Any]:
        """Perform the MCP initialize handshake once and return its result."""
        if self._initialize_result is not None:
            return self._initialize_result

        async with self._initialize_lock:
            if self._initialize_result is not None:
                return self._initialize_result
            result = await self._request(
                method="initialize",
                params={
                    "protocolVersion": self.config.protocol_version,
                    "capabilities": {},
                    "clientInfo": {
                        "name": self.config.client_name,
                        "version": self.config.client_version,
                    },
                },
                request_id=f"initialize-{uuid4().hex}",
            )
            if not isinstance(result, Mapping) or not isinstance(result.get("capabilities", {}), Mapping):
                raise RemoteMCPTransportError(
                    "protocol_error",
                    "The remote MCP server returned an invalid initialize result.",
                )
            await self._notification("notifications/initialized", {})
            self._initialize_result = dict(result)
            return self._initialize_result

    async def list_tools(self) -> tuple[Mapping[str, Any], ...]:
        """Return only remote tool declarations that are in the local allowlist."""
        await self.initialize()
        result = await self._request(method="tools/list", params={}, request_id=f"tools-list-{uuid4().hex}")
        if not isinstance(result, Mapping) or not isinstance(result.get("tools"), list):
            raise RemoteMCPTransportError("protocol_error", "The remote MCP server returned an invalid tool list.")

        tools: list[Mapping[str, Any]] = []
        for tool in result["tools"]:
            if not isinstance(tool, Mapping) or not isinstance(tool.get("name"), str):
                raise RemoteMCPTransportError("protocol_error", "The remote MCP server returned an invalid tool list.")
            if tool["name"] in self.config.allowed_tools:
                tools.append(dict(tool))
        return tuple(tools)

    async def execute(self, request: MCPExecutionRequest) -> Mapping[str, Any]:
        """Call one allowlisted remote MCP tool and return its result object."""
        if request.tool_name not in self.config.allowed_tools:
            raise RemoteMCPTransportError(
                "tool_not_allowed",
                "The remote MCP tool is not allowed for the current project.",
            )
        await self.initialize()
        result = await self._request(
            method="tools/call",
            params={"name": request.tool_name, "arguments": dict(request.arguments)},
            request_id=request.request_id,
        )
        if not isinstance(result, Mapping):
            raise RemoteMCPTransportError("protocol_error", "The remote MCP server returned an invalid tool result.")
        if result.get("isError") is True:
            raise RemoteMCPTransportError(_REMOTE_TOOL_FAILED_CODE, _REMOTE_TOOL_FAILED_MESSAGE)
        return dict(result)

    async def cancel(self, request_id: str) -> None:
        """Best-effort MCP cancellation notification for an in-flight request."""
        if not request_id or self._initialize_result is None:
            return
        try:
            await self._notification(
                "notifications/cancelled",
                {"requestId": request_id, "reason": "cancelled"},
            )
        except asyncio.CancelledError:
            raise
        except Exception:
            # Cancellation is advisory and must not hide the original failure.
            return

    async def aclose(self) -> None:
        """Close the injected client only when this adapter owns it."""
        if self._owns_client and not self._closed:
            self._closed = True
            await self._client.aclose()

    async def __aenter__(self) -> RemoteMCPTransport:
        return self

    async def __aexit__(self, exc_type: Any, exc_value: Any, traceback: Any) -> None:
        await self.aclose()

    async def _notification(self, method: str, params: Mapping[str, Any]) -> None:
        await self._post(
            {"jsonrpc": _JSON_RPC_VERSION, "method": method, "params": dict(params)},
        )

    async def _request(self, *, method: str, params: Mapping[str, Any], request_id: str) -> Any:
        response = await self._post(
            {"jsonrpc": _JSON_RPC_VERSION, "id": request_id, "method": method, "params": dict(params)},
        )
        if not isinstance(response, Mapping):
            raise RemoteMCPTransportError(
                "protocol_error", "The remote MCP server returned an invalid JSON-RPC response."
            )
        if response.get("jsonrpc") != _JSON_RPC_VERSION or response.get("id") != request_id:
            raise RemoteMCPTransportError(
                "protocol_error", "The remote MCP server returned an invalid JSON-RPC response."
            )
        if "error" in response:
            if method == "tools/call":
                raise RemoteMCPTransportError(_REMOTE_TOOL_FAILED_CODE, _REMOTE_TOOL_FAILED_MESSAGE)
            raise RemoteMCPTransportError("remote_request_failed", "The remote MCP request failed.")
        if "result" not in response:
            raise RemoteMCPTransportError(
                "protocol_error", "The remote MCP server returned an invalid JSON-RPC response."
            )
        return response["result"]

    async def _post(self, payload: Mapping[str, Any]) -> Any:
        try:
            encoded = json.dumps(payload, allow_nan=False, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise RemoteMCPTransportError("invalid_request", "The MCP request could not be encoded.") from exc
        if len(encoded) > self.config.max_request_bytes:
            raise RemoteMCPTransportError("request_too_large", "The MCP request exceeds its size limit.")

        try:
            status_code, response_headers, response_content = await asyncio.wait_for(
                self._post_once(encoded),
                timeout=self.config.timeout_seconds,
            )
        except asyncio.CancelledError:
            raise
        except TimeoutError:
            raise RemoteMCPTransportError("remote_timeout", "The remote MCP request timed out.") from None
        except httpx.HTTPError:
            raise RemoteMCPTransportError("remote_unavailable", "The remote MCP server is unavailable.") from None

        declared_length = response_headers.get("content-length")
        if declared_length is not None:
            try:
                if int(declared_length) > self.config.max_response_bytes:
                    raise RemoteMCPTransportError(
                        "response_too_large", "The remote MCP response exceeds its size limit."
                    )
            except ValueError:
                raise RemoteMCPTransportError(
                    "protocol_error", "The remote MCP server returned an invalid response."
                ) from None
        if status_code < 200 or status_code >= 300:
            raise RemoteMCPTransportError(*_map_http_status(status_code))
        if not response_content:
            return None
        try:
            return json.loads(response_content)
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RemoteMCPTransportError("protocol_error", "The remote MCP server returned invalid JSON.") from exc

    async def _post_once(self, encoded: bytes) -> tuple[int, httpx.Headers, bytes]:
        async with self._client.stream(
            "POST",
            self.config.endpoint,
            content=encoded,
            headers={
                "accept": "application/json",
                "content-type": "application/json",
                **self._headers,
                **({"mcp-session-id": self._session_id} if self._session_id is not None else {}),
            },
            timeout=self.config.timeout_seconds,
        ) as response:
            declared_length = response.headers.get("content-length")
            if declared_length is not None:
                try:
                    if int(declared_length) > self.config.max_response_bytes:
                        raise RemoteMCPTransportError(
                            "response_too_large",
                            "The remote MCP response exceeds its size limit.",
                        )
                except ValueError:
                    raise RemoteMCPTransportError(
                        "protocol_error",
                        "The remote MCP server returned an invalid response.",
                    ) from None

            chunks: list[bytes] = []
            size = 0
            async for chunk in response.aiter_bytes():
                size += len(chunk)
                if size > self.config.max_response_bytes:
                    raise RemoteMCPTransportError(
                        "response_too_large",
                        "The remote MCP response exceeds its size limit.",
                    )
                chunks.append(chunk)
            session_id = response.headers.get("mcp-session-id")
            if session_id:
                self._session_id = session_id
            return response.status_code, response.headers, b"".join(chunks)


def _validate_headers(headers: Mapping[Any, Any]) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for name, value in headers.items():
        if not isinstance(name, str) or not isinstance(value, str) or not name.strip():
            raise ValueError("Remote MCP headers must use non-empty string names and values.")
        if name.lower() in _BLOCKED_HEADERS:
            raise ValueError(f"Remote MCP header {name!r} is managed by the transport.")
        normalized[name] = value
    return normalized


def _map_http_status(status_code: int) -> tuple[str, str]:
    if status_code in {401, 403}:
        return "remote_unauthorized", "The remote MCP server rejected authorization."
    if status_code in {404, 405}:
        return "remote_endpoint_not_found", "The remote MCP endpoint is not available."
    if status_code == 429:
        return "remote_rate_limited", "The remote MCP server is rate limiting requests."
    return "remote_unavailable", "The remote MCP server rejected the request."


class RemoteMCPRuntime:
    """Build a broker from one initialized, allowlisted remote MCP transport."""

    def __init__(
        self,
        transport: RemoteMCPTransport,
        *,
        adapter_id: str = "remote-mcp",
        audit_sink: MCPAuditSink | None = None,
    ) -> None:
        if not adapter_id:
            raise ValueError("Remote MCP adapter_id must not be empty.")
        self._transport = transport
        self._adapter_id = adapter_id
        self._audit_sink = audit_sink

    async def build_broker(self) -> MCPToolBroker:
        """Discover remote tools and expose only safe broker read-only definitions."""
        await self._transport.initialize()
        remote_tools = await self._transport.list_tools()
        definitions: list[MCPToolDefinition] = []
        names: set[str] = set()

        for raw_tool in remote_tools:
            tool: Any = raw_tool
            if not isinstance(tool, Mapping):
                raise RemoteMCPTransportError(
                    "protocol_error",
                    "The remote MCP server returned an invalid tool definition.",
                )
            name = tool.get("name")
            schema = tool.get("inputSchema")
            if not isinstance(name, str) or not name or not isinstance(schema, Mapping):
                raise RemoteMCPTransportError(
                    "protocol_error",
                    "The remote MCP server returned an invalid tool definition.",
                )
            if name not in self._transport.config.allowed_tools:
                continue
            if name in names:
                raise RemoteMCPTransportError(
                    "protocol_error",
                    "The remote MCP server returned duplicate tool definitions.",
                )
            names.add(name)
            definitions.append(
                MCPToolDefinition(
                    name=name,
                    adapter_id=self._adapter_id,
                    operation=ToolOperation.READ_ONLY,
                    input_schema=dict(schema),
                    timeout_seconds=self._transport.config.timeout_seconds,
                )
            )

        return MCPToolBroker(
            tools=definitions,
            adapters={self._adapter_id: self._transport},
            allowed_tools=names,
            audit_sink=self._audit_sink,
        )

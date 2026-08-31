"""First-stage broker for in-process and remote MCP tools.

The broker is intentionally transport-agnostic.  Its public seam is
:meth:`MCPToolBroker.execute`; local SDK adapters and a future remote transport
adapter satisfy the same ``MCPToolAdapter`` protocol.  This first stage permits
only read-only tools and deliberately has no network implementation.
"""

from __future__ import annotations

import asyncio
import logging
import math
from collections.abc import Iterable, Mapping, Set
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal, Protocol
from uuid import uuid4

logger = logging.getLogger(__name__)


class ToolOperation(StrEnum):
    """Authority a tool requests from the broker."""

    READ_ONLY = "read_only"
    WRITE = "write"
    ADMIN = "admin"


@dataclass(frozen=True, slots=True)
class MCPToolDefinition:
    """A broker-owned tool declaration.

    ``input_schema`` supports the safe JSON Schema subset needed by the first
    stage: ``type``, ``required``, ``properties``, ``additionalProperties``,
    ``items`` and ``enum``.  Broader schema keywords must not silently claim
    validation until the broker adopts a full JSON Schema validator.
    """

    name: str
    adapter_id: str
    operation: ToolOperation
    input_schema: Mapping[str, Any]
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.name:
            raise ValueError("MCP tool names must not be empty.")
        if not self.adapter_id:
            raise ValueError("MCP tool adapter ids must not be empty.")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("MCP tool timeout_seconds must be finite and greater than zero.")


@dataclass(frozen=True, slots=True)
class MCPExecutionRequest:
    """Context passed unchanged to an in-process or remote adapter."""

    tool_name: str
    arguments: Mapping[str, Any]
    request_id: str
    trace_id: str


@dataclass(frozen=True, slots=True)
class MCPBrokerError:
    """Stable, safe error result returned by the broker."""

    code: str
    message: str
    details: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MCPExecutionResult:
    """Result observed by callers of the broker's public seam."""

    ok: bool
    request_id: str
    trace_id: str
    payload: Mapping[str, Any] | None = None
    error: MCPBrokerError | None = None


AuditOutcome = Literal["succeeded", "rejected", "failed", "timed_out", "cancelled"]


@dataclass(frozen=True, slots=True)
class MCPAuditEvent:
    """Transport-neutral audit record emitted once for each execution attempt."""

    tool_name: str
    request_id: str
    trace_id: str
    outcome: AuditOutcome
    error_code: str | None = None


class MCPToolAdapter(Protocol):
    """Uniform seam for local SDK and future remote MCP transports."""

    async def execute(self, request: MCPExecutionRequest) -> Mapping[str, Any]:
        """Execute a tool request and return a JSON-compatible object result."""
        ...

    async def cancel(self, request_id: str) -> None:
        """Best-effort cancellation for an in-flight request."""
        ...


class MCPAuditSink(Protocol):
    """Persistence seam for an execution audit trail."""

    async def record(self, event: MCPAuditEvent) -> None:
        """Persist one audit record."""
        ...


class _NullAuditSink:
    async def record(self, event: MCPAuditEvent) -> None:
        del event


class MCPToolBroker:
    """Authorize, validate, execute, time-box and audit first-stage MCP calls.

    ``execute()`` is the only public execution seam.  It deliberately returns
    normalized error results instead of surfacing adapter exceptions.  Caller
    cancellation propagates to the selected adapter and then remains a normal
    ``asyncio.CancelledError`` for the caller to handle.
    """

    def __init__(
        self,
        *,
        tools: Iterable[MCPToolDefinition],
        adapters: Mapping[str, MCPToolAdapter],
        allowed_tools: Set[str],
        audit_sink: MCPAuditSink | None = None,
    ) -> None:
        definitions = list(tools)
        self._tools = {definition.name: definition for definition in definitions}
        if len(self._tools) != len(definitions):
            raise ValueError("MCP tool names must be unique.")
        self._adapters = dict(adapters)
        self._allowed_tools = frozenset(allowed_tools)
        self._audit_sink: MCPAuditSink = audit_sink or _NullAuditSink()

    async def execute(
        self,
        tool_name: str,
        arguments: Mapping[str, Any],
        *,
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> MCPExecutionResult:
        """Execute one allowlisted read-only tool through its registered adapter."""
        request_id = request_id or uuid4().hex
        trace_id = trace_id or uuid4().hex

        definition = self._tools.get(tool_name)
        if definition is None or tool_name not in self._allowed_tools:
            return await self._reject(
                tool_name=tool_name,
                request_id=request_id,
                trace_id=trace_id,
                code="tool_not_allowed",
                message="This MCP tool is not allowed for the current project.",
            )
        if definition.operation is not ToolOperation.READ_ONLY:
            return await self._reject(
                tool_name=tool_name,
                request_id=request_id,
                trace_id=trace_id,
                code="operation_not_supported",
                message="Only read-only MCP tools are supported in this stage.",
            )

        validation_error = _validate_json_schema(definition.input_schema, arguments)
        if validation_error is not None:
            return await self._reject(
                tool_name=tool_name,
                request_id=request_id,
                trace_id=trace_id,
                code="invalid_arguments",
                message="The MCP tool arguments do not match its declared schema.",
                details=validation_error,
            )

        adapter = self._adapters.get(definition.adapter_id)
        if adapter is None:
            return await self._reject(
                tool_name=tool_name,
                request_id=request_id,
                trace_id=trace_id,
                code="adapter_unavailable",
                message="The MCP tool is temporarily unavailable.",
            )

        request = MCPExecutionRequest(
            tool_name=tool_name,
            arguments=dict(arguments),
            request_id=request_id,
            trace_id=trace_id,
        )
        try:
            payload: Any = await asyncio.wait_for(adapter.execute(request), timeout=definition.timeout_seconds)
        except TimeoutError:
            await self._cancel_adapter(adapter, request_id)
            error = MCPBrokerError(
                code="tool_timeout",
                message="The MCP tool did not complete before its timeout.",
                details={"timeout_seconds": definition.timeout_seconds},
            )
            await self._audit(tool_name, request_id, trace_id, "timed_out", error.code)
            return MCPExecutionResult(ok=False, request_id=request_id, trace_id=trace_id, error=error)
        except asyncio.CancelledError:
            await asyncio.shield(self._cancel_adapter(adapter, request_id))
            await asyncio.shield(self._audit(tool_name, request_id, trace_id, "cancelled"))
            raise
        except Exception:
            logger.exception("MCP adapter execution failed tool=%s request_id=%s", tool_name, request_id)
            error = MCPBrokerError(
                code="adapter_execution_failed",
                message="The MCP tool could not complete the request.",
                details={},
            )
            await self._audit(tool_name, request_id, trace_id, "failed", error.code)
            return MCPExecutionResult(ok=False, request_id=request_id, trace_id=trace_id, error=error)

        if not isinstance(payload, Mapping):
            error = MCPBrokerError(
                code="adapter_invalid_response",
                message="The MCP tool returned an invalid response.",
                details={},
            )
            await self._audit(tool_name, request_id, trace_id, "failed", error.code)
            return MCPExecutionResult(ok=False, request_id=request_id, trace_id=trace_id, error=error)

        await self._audit(tool_name, request_id, trace_id, "succeeded")
        return MCPExecutionResult(ok=True, request_id=request_id, trace_id=trace_id, payload=dict(payload))

    async def _reject(
        self,
        *,
        tool_name: str,
        request_id: str,
        trace_id: str,
        code: str,
        message: str,
        details: Mapping[str, Any] | None = None,
    ) -> MCPExecutionResult:
        error = MCPBrokerError(code=code, message=message, details=details or {})
        await self._audit(tool_name, request_id, trace_id, "rejected", error.code)
        return MCPExecutionResult(ok=False, request_id=request_id, trace_id=trace_id, error=error)

    async def _cancel_adapter(self, adapter: MCPToolAdapter, request_id: str) -> None:
        try:
            await adapter.cancel(request_id)
        except Exception:
            logger.warning("MCP adapter cancellation failed request_id=%s", request_id, exc_info=True)

    async def _audit(
        self,
        tool_name: str,
        request_id: str,
        trace_id: str,
        outcome: AuditOutcome,
        error_code: str | None = None,
    ) -> None:
        try:
            await self._audit_sink.record(
                MCPAuditEvent(
                    tool_name=tool_name,
                    request_id=request_id,
                    trace_id=trace_id,
                    outcome=outcome,
                    error_code=error_code,
                )
            )
        except Exception:
            logger.warning("MCP audit sink failed request_id=%s", request_id, exc_info=True)


def _validate_json_schema(schema: Mapping[str, Any], value: Any, path: str = "$") -> dict[str, str] | None:
    """Validate the intentionally small first-stage JSON Schema subset."""
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, Mapping):
            return {"path": path, "reason": "expected object"}
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return {"path": path, "reason": "invalid tool schema"}
        required = schema.get("required", [])
        if not isinstance(required, list) or not all(isinstance(key, str) for key in required):
            return {"path": path, "reason": "invalid tool schema"}
        for key in required:
            if key not in value:
                return {"path": path, "reason": f"missing required property {key!r}"}
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in properties:
                    return {"path": f"{path}.{key}", "reason": "unexpected property"}
        for key, property_schema in properties.items():
            if key not in value:
                continue
            if not isinstance(key, str) or not isinstance(property_schema, Mapping):
                return {"path": path, "reason": "invalid tool schema"}
            error = _validate_json_schema(property_schema, value[key], f"{path}.{key}")
            if error is not None:
                return error
    elif expected_type == "array":
        if not isinstance(value, list):
            return {"path": path, "reason": "expected array"}
        item_schema = schema.get("items")
        if item_schema is not None:
            if not isinstance(item_schema, Mapping):
                return {"path": path, "reason": "invalid tool schema"}
            for index, item in enumerate(value):
                error = _validate_json_schema(item_schema, item, f"{path}[{index}]")
                if error is not None:
                    return error
    elif expected_type == "string" and not isinstance(value, str):
        return {"path": path, "reason": "expected string"}
    elif expected_type == "integer" and (not isinstance(value, int) or isinstance(value, bool)):
        return {"path": path, "reason": "expected integer"}
    elif expected_type == "number" and (not isinstance(value, (int, float)) or isinstance(value, bool)):
        return {"path": path, "reason": "expected number"}
    elif expected_type == "boolean" and not isinstance(value, bool):
        return {"path": path, "reason": "expected boolean"}
    elif expected_type == "null" and value is not None:
        return {"path": path, "reason": "expected null"}
    elif expected_type is not None and expected_type not in {
        "object",
        "array",
        "string",
        "integer",
        "number",
        "boolean",
        "null",
    }:
        return {"path": path, "reason": "invalid tool schema"}

    enum = schema.get("enum")
    if enum is not None:
        if not isinstance(enum, list):
            return {"path": path, "reason": "invalid tool schema"}
        if value not in enum:
            return {"path": path, "reason": "value is not an allowed enum member"}
    return None

"""Runtime configuration and SDK manifest bridge for remote MCP servers."""

from __future__ import annotations

import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from claude_agent_sdk import SdkMcpTool, create_sdk_mcp_server, tool

from .mcp_broker import MCPToolBroker
from .remote_mcp_transport import RemoteMCPRuntime, RemoteMCPTransport, RemoteMCPTransportConfig

FIRST_STAGE_REMOTE_TOOL_ALLOWLIST = frozenset(
    {
        "knowledge.search",
        "knowledge.open",
        "knowledge.graph",
        "provider.capabilities",
        "provider.status",
    }
)
_CONFIG_FILENAMES = ("remote_mcp.json", ".shotwise_remote_mcp.json")
_SERVER_NAME_RE = re.compile(r"^[A-Za-z0-9_-]{1,48}$")
_MAX_SERVERS = 8
_MAX_ALLOWLIST_SIZE = 64


class RemoteMCPConfigError(ValueError):
    """Raised when a remote MCP configuration is invalid or unsafe."""


@dataclass(frozen=True, slots=True)
class RemoteMCPServerSpec:
    """Configuration for one remote MCP endpoint."""

    name: str
    endpoint: str
    allowed_tools: frozenset[str]
    headers: Mapping[str, str] = field(default_factory=dict)
    timeout_seconds: float = 30.0
    max_request_bytes: int = 64 * 1024
    max_response_bytes: int = 1024 * 1024
    protocol_version: str = "2025-06-18"
    client_name: str = "shotwise"
    client_version: str = "0.1"

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str) -> RemoteMCPServerSpec:
        name = value.get("name")
        endpoint = value.get("endpoint")
        raw_tools = value.get("allowed_tools", value.get("allowlist"))
        if not isinstance(name, str) or not _SERVER_NAME_RE.fullmatch(name):
            raise RemoteMCPConfigError(f"Invalid remote MCP server name in {source}.")
        if name == "shotwise":
            raise RemoteMCPConfigError("The remote MCP server name 'shotwise' is reserved.")
        if not isinstance(endpoint, str) or not endpoint:
            raise RemoteMCPConfigError(f"Remote MCP server {name!r} needs an endpoint.")
        if not isinstance(raw_tools, Sequence) or isinstance(raw_tools, (str, bytes)):
            raise RemoteMCPConfigError(f"Remote MCP server {name!r} needs an allowlist.")
        allowed_tools = frozenset(raw_tools)
        if (
            not allowed_tools
            or len(allowed_tools) > _MAX_ALLOWLIST_SIZE
            or any(
                not isinstance(tool_name, str) or not tool_name or tool_name not in FIRST_STAGE_REMOTE_TOOL_ALLOWLIST
                for tool_name in allowed_tools
            )
        ):
            raise RemoteMCPConfigError(
                f"Remote MCP server {name!r} contains a tool outside the first-stage read-only allowlist."
            )
        raw_headers = value.get("headers", {})
        if not isinstance(raw_headers, Mapping):
            raise RemoteMCPConfigError(f"Remote MCP server {name!r} headers must be an object.")
        if any(not isinstance(key, str) or not isinstance(item, str) for key, item in raw_headers.items()):
            raise RemoteMCPConfigError(f"Remote MCP server {name!r} headers must contain strings.")
        headers = {key: item for key, item in raw_headers.items()}
        try:
            spec = cls(
                name=name,
                endpoint=endpoint,
                allowed_tools=allowed_tools,
                headers=headers,
                timeout_seconds=float(value.get("timeout_seconds", 30.0)),
                max_request_bytes=int(value.get("max_request_bytes", 64 * 1024)),
                max_response_bytes=int(value.get("max_response_bytes", 1024 * 1024)),
                protocol_version=str(value.get("protocol_version", "2025-06-18")),
                client_name=str(value.get("client_name", "shotwise")),
                client_version=str(value.get("client_version", "0.1")),
            )
            RemoteMCPTransportConfig(
                spec.endpoint,
                allowed_tools=spec.allowed_tools,
                timeout_seconds=spec.timeout_seconds,
                max_request_bytes=spec.max_request_bytes,
                max_response_bytes=spec.max_response_bytes,
                protocol_version=spec.protocol_version,
                client_name=spec.client_name,
                client_version=spec.client_version,
            )
        except (TypeError, ValueError) as exc:
            raise RemoteMCPConfigError(f"Invalid remote MCP server {name!r} configuration.") from exc
        return spec


@dataclass(frozen=True, slots=True)
class RemoteMCPConfig:
    """Effective profile/project remote MCP configuration."""

    servers: tuple[RemoteMCPServerSpec, ...] = ()

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], *, source: str) -> RemoteMCPConfig:
        raw_servers = value.get("servers", value.get("remote_mcp_servers", []))
        if not isinstance(raw_servers, Sequence) or isinstance(raw_servers, (str, bytes)):
            raise RemoteMCPConfigError(f"Remote MCP servers in {source} must be an array.")
        if len(raw_servers) > _MAX_SERVERS:
            raise RemoteMCPConfigError("Too many remote MCP servers are configured.")
        servers = tuple(
            RemoteMCPServerSpec.from_mapping(server, source=source)
            for server in raw_servers
            if isinstance(server, Mapping)
        )
        if len(servers) != len(raw_servers):
            raise RemoteMCPConfigError(f"Remote MCP servers in {source} must contain objects.")
        if len({server.name for server in servers}) != len(servers):
            raise RemoteMCPConfigError(f"Remote MCP server names in {source} must be unique.")
        return cls(servers=servers)

    def merge(self, override: RemoteMCPConfig, *, source: str) -> RemoteMCPConfig:
        """Merge project settings without allowing them to widen profile policy."""
        profile_by_name = {server.name: server for server in self.servers}
        merged = dict(profile_by_name)
        for project_server in override.servers:
            profile_server = profile_by_name.get(project_server.name)
            if profile_server is None:
                merged[project_server.name] = project_server
                continue
            if profile_server.endpoint != project_server.endpoint:
                raise RemoteMCPConfigError(f"Remote MCP endpoint conflict for {project_server.name!r} in {source}.")
            effective_tools = profile_server.allowed_tools & project_server.allowed_tools
            if not effective_tools:
                merged.pop(project_server.name, None)
                continue
            merged[project_server.name] = RemoteMCPServerSpec(
                name=profile_server.name,
                endpoint=profile_server.endpoint,
                allowed_tools=frozenset(effective_tools),
                headers=profile_server.headers,
                timeout_seconds=min(profile_server.timeout_seconds, project_server.timeout_seconds),
                max_request_bytes=min(profile_server.max_request_bytes, project_server.max_request_bytes),
                max_response_bytes=min(profile_server.max_response_bytes, project_server.max_response_bytes),
                protocol_version=profile_server.protocol_version,
                client_name=profile_server.client_name,
                client_version=profile_server.client_version,
            )
        return RemoteMCPConfig(tuple(merged.values()))


def load_remote_mcp_config(project_root: Path, profile_root: Path | None = None) -> RemoteMCPConfig:
    """Load profile defaults and project overrides from local JSON files."""
    effective = RemoteMCPConfig()
    if profile_root is not None:
        for path in _candidate_paths(profile_root):
            effective = effective.merge(_read_config(path), source=str(path))
    for path in _candidate_paths(project_root):
        effective = effective.merge(_read_config(path), source=str(path))

    project_json = project_root / "project.json"
    if project_json.is_file():
        try:
            raw = json.loads(project_json.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RemoteMCPConfigError("The project configuration could not be read.") from exc
        embedded = raw.get("remote_mcp") if isinstance(raw, Mapping) else None
        if embedded is not None:
            if not isinstance(embedded, Mapping):
                raise RemoteMCPConfigError("project.json remote_mcp must be an object.")
            effective = effective.merge(
                RemoteMCPConfig.from_mapping(embedded, source=str(project_json)),
                source=str(project_json),
            )
    return effective


def _candidate_paths(root: Path) -> tuple[Path, ...]:
    paths: list[Path] = []
    for base in (root, root / ".claude"):
        for filename in _CONFIG_FILENAMES:
            path = base / filename
            if path.is_file():
                paths.append(path)
    return tuple(paths)


def _read_config(path: Path) -> RemoteMCPConfig:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RemoteMCPConfigError(f"Remote MCP configuration {path} could not be read.") from exc
    if not isinstance(raw, Mapping):
        raise RemoteMCPConfigError(f"Remote MCP configuration {path} must be an object.")
    return RemoteMCPConfig.from_mapping(raw, source=str(path))


@dataclass(slots=True)
class RemoteMCPManifest:
    """Claude SDK server configs and their owned transports."""

    servers: dict[str, Any]
    allowed_tools: tuple[str, ...]
    _transports: list[RemoteMCPTransport]

    @property
    def has_resources(self) -> bool:
        return bool(self._transports)

    async def aclose(self) -> None:
        transports = tuple(self._transports)
        self._transports.clear()
        errors: list[Exception] = []
        for transport in transports:
            try:
                await transport.aclose()
            except Exception as exc:
                errors.append(exc)
        if errors:
            raise errors[0]


async def build_remote_mcp_manifest(config: RemoteMCPConfig) -> RemoteMCPManifest:
    """Handshake remote servers and expose brokered read-only tools to Claude."""
    servers: dict[str, Any] = {}
    allowed_tools: list[str] = []
    transports: list[RemoteMCPTransport] = []
    try:
        for spec in config.servers:
            transport = RemoteMCPTransport(
                spec.endpoint,
                allowed_tools=spec.allowed_tools,
                headers=spec.headers,
                timeout_seconds=spec.timeout_seconds,
                max_request_bytes=spec.max_request_bytes,
                max_response_bytes=spec.max_response_bytes,
                protocol_version=spec.protocol_version,
                client_name=spec.client_name,
                client_version=spec.client_version,
            )
            transports.append(transport)
            broker = await RemoteMCPRuntime(transport, adapter_id=f"remote-mcp:{spec.name}").build_broker()
            server_name = f"remote_{spec.name}"
            servers[server_name] = create_sdk_mcp_server(
                name=server_name,
                version="1.0.0",
                tools=_build_sdk_tools(broker),
            )
            allowed_tools.extend(f"mcp__{server_name}__{tool_name}" for tool_name in broker.tool_names)
    except Exception:
        manifest = RemoteMCPManifest(servers={}, allowed_tools=(), _transports=transports)
        try:
            await manifest.aclose()
        except Exception:
            pass
        raise
    return RemoteMCPManifest(servers=servers, allowed_tools=tuple(allowed_tools), _transports=transports)


def _build_sdk_tools(broker: MCPToolBroker) -> list[SdkMcpTool[Any]]:
    sdk_tools: list[SdkMcpTool[Any]] = []
    for definition in broker.definitions:
        sdk_tool = tool(
            definition.name,
            f"Read-only remote MCP query: {definition.name}",
            dict(definition.input_schema),
        )(_build_sdk_handler(broker, definition.name))
        sdk_tools.append(sdk_tool)
    return sdk_tools


def _build_sdk_handler(broker: MCPToolBroker, tool_name: str) -> Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]:
    async def handler(args: dict[str, Any]) -> dict[str, Any]:
        result = await broker.execute(tool_name, args)
        if result.ok and result.payload is not None:
            return dict(result.payload)
        error = result.error
        return {
            "content": [{"type": "text", "text": error.message if error else "The MCP tool failed."}],
            "is_error": True,
        }

    return handler

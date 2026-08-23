"""Safety validation for marketplace workflow contracts."""

from __future__ import annotations

import math
import re
from collections.abc import Collection, Mapping, Sequence
from typing import Any

_SCHEMA_TYPES = frozenset({"array", "boolean", "integer", "null", "number", "object", "string"})
_RESOURCE_KEYS = frozenset(
    {
        "resource_ref",
        "resource_refs",
        "resource_path",
        "asset_ref",
        "asset_refs",
        "asset_path",
        "media_asset_id",
        "media_asset_ids",
    }
)
_WINDOWS_ABSOLUTE_RE = re.compile(r"^(?:[A-Za-z]:[\/]|\\)")
_GENERATION_MODES = frozenset({"storyboard", "reference_video"})


class WorkflowContractValidationError(ValueError):
    """Raised when an uploaded workflow contract is unsafe or malformed."""

    def __init__(self, issues: Sequence[Mapping[str, Any]]) -> None:
        self.issues = tuple(dict(issue) for issue in issues)
        summary = "; ".join(
            f"{issue.get('code', 'invalid_contract')} at {issue.get('path', '$')}" for issue in self.issues
        )
        super().__init__(summary or "invalid workflow contract")


def validate_workflow_template_contract(
    contract: Mapping[str, Any],
    *,
    allowed_executor_ids: Collection[str] | None = None,
    available_capabilities: Collection[str] | None = None,
) -> dict[str, Any]:
    """Validate template metadata, node schemas, references, and graph safety."""

    issues: list[dict[str, Any]] = []
    if not isinstance(contract, Mapping):
        raise WorkflowContractValidationError(
            ({"code": "contract_not_object", "path": "$", "message": "contract must be an object"},)
        )

    generation_mode = contract.get("generation_mode")
    if generation_mode is not None and generation_mode not in _GENERATION_MODES:
        _issue(issues, "invalid_generation_mode", "$.generation_mode", "generation_mode is unsupported")

    input_schema = contract.get("input_schema")
    if input_schema is not None:
        _validate_json_schema(input_schema, "$.input_schema", issues)
    for field in ("risk_tags", "required_capabilities", "provider_requirements"):
        value = contract.get(field)
        if value is not None:
            _validate_string_sequence(value, f"$.{field}", issues)
    for field in ("estimated_episode_cost", "estimated_cost"):
        value = contract.get(field)
        if value is not None and (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or value < 0
        ):
            _issue(issues, "invalid_cost", f"$.{field}", "cost must be a finite non-negative number")

    nodes = contract.get("nodes", [])
    edges = contract.get("edges", [])
    if not isinstance(nodes, list):
        _issue(issues, "nodes_not_array", "$.nodes", "nodes must be an array")
        nodes = []
    if not isinstance(edges, list):
        _issue(issues, "edges_not_array", "$.edges", "edges must be an array")
        edges = []

    node_ids: list[str] = []
    node_id_set: set[str] = set()
    for index, node in enumerate(nodes):
        path = f"$.nodes[{index}]"
        if not isinstance(node, Mapping):
            _issue(issues, "node_not_object", path, "node must be an object")
            continue
        node_id = node.get("node_key", node.get("id", node.get("node_id")))
        if not isinstance(node_id, str) or not node_id.strip():
            _issue(issues, "node_id_required", f"{path}.id", "node id must be a non-empty string")
            continue
        if node_id in node_id_set:
            _issue(issues, "duplicate_node_id", f"{path}.id", f"duplicate node id: {node_id}")
        else:
            node_id_set.add(node_id)
            node_ids.append(node_id)
        for schema_field in ("input_schema", "output_schema"):
            schema = node.get(schema_field)
            if schema is not None:
                _validate_json_schema(schema, f"{path}.{schema_field}", issues)
        _validate_node_contract(
            node,
            path,
            issues,
            allowed_executor_ids=allowed_executor_ids,
            available_capabilities=available_capabilities,
        )
        _validate_resource_references(node, path, issues)

    adjacency: dict[str, set[str]] = {node_id: set() for node_id in node_id_set}
    indegree = {node_id: 0 for node_id in node_id_set}
    seen_edges: set[tuple[str, str]] = set()
    missing_endpoints: list[dict[str, Any]] = []
    for index, edge in enumerate(edges):
        path = f"$.edges[{index}]"
        if not isinstance(edge, Mapping):
            _issue(issues, "edge_not_object", path, "edge must be an object")
            continue
        source = _edge_endpoint(edge, "source")
        target = _edge_endpoint(edge, "target")
        if source is None or target is None:
            _issue(issues, "edge_endpoint_required", path, "edge needs source and target node ids")
            continue
        missing = [node_id for node_id in (source, target) if node_id not in node_id_set]
        if missing:
            missing_endpoints.append({"edge_index": index, "missing": missing})
            _issue(issues, "missing_edge_endpoint", path, f"unknown node id: {', '.join(missing)}")
            continue
        pair = (source, target)
        if pair in seen_edges:
            _issue(issues, "duplicate_edge", path, f"duplicate edge: {source} -> {target}")
            continue
        seen_edges.add(pair)
        adjacency[source].add(target)
        indegree[target] += 1

    queue = [node_id for node_id in node_ids if indegree[node_id] == 0]
    visited: list[str] = []
    while queue:
        current = queue.pop(0)
        visited.append(current)
        for target in adjacency[current]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(visited) != len(node_id_set):
        cycle_nodes = [node_id for node_id in node_ids if node_id not in visited]
        _issue(
            issues, "workflow_cycle_detected", "$.edges", f"workflow graph contains a cycle: {', '.join(cycle_nodes)}"
        )

    if issues:
        raise WorkflowContractValidationError(issues)
    return {
        "valid": True,
        "node_count": len(node_ids),
        "edge_count": len(seen_edges),
        "missing_endpoints": missing_endpoints,
    }


def _validate_node_contract(
    node: Mapping[str, Any],
    path: str,
    issues: list[dict[str, Any]],
    *,
    allowed_executor_ids: Collection[str] | None,
    available_capabilities: Collection[str] | None,
) -> None:
    executor_id = node.get("executor_id")
    if executor_id is not None:
        if not isinstance(executor_id, str) or not executor_id.strip():
            _issue(issues, "invalid_executor_id", f"{path}.executor_id", "executor_id must be a non-empty string")
        elif allowed_executor_ids is not None and executor_id not in allowed_executor_ids:
            _issue(issues, "unknown_executor_id", f"{path}.executor_id", f"executor is not allowed: {executor_id}")
    capabilities = node.get("required_capabilities")
    if capabilities is not None:
        _validate_string_sequence(capabilities, f"{path}.required_capabilities", issues)
        if available_capabilities is not None and isinstance(capabilities, list):
            unavailable = sorted(set(capabilities) - set(available_capabilities))
            if unavailable:
                _issue(
                    issues,
                    "capability_unavailable",
                    f"{path}.required_capabilities",
                    f"capabilities are unavailable: {', '.join(unavailable)}",
                )
    estimated_cost = node.get("estimated_cost")
    if estimated_cost is not None and (
        isinstance(estimated_cost, bool)
        or not isinstance(estimated_cost, (int, float))
        or not math.isfinite(float(estimated_cost))
        or estimated_cost < 0
    ):
        _issue(issues, "invalid_cost", f"{path}.estimated_cost", "estimated_cost must be a finite non-negative number")
    for field in ("cache_policy", "approval_policy"):
        value = node.get(field)
        if value is not None and not isinstance(value, (str, Mapping)):
            _issue(issues, "invalid_node_policy", f"{path}.{field}", "policy must be a string or object")


def _validate_json_schema(value: Any, path: str, issues: list[dict[str, Any]], depth: int = 0) -> None:
    if depth > 32:
        _issue(issues, "schema_too_deep", path, "schema nesting exceeds the supported limit")
        return
    if not isinstance(value, Mapping):
        _issue(issues, "schema_not_object", path, "JSON Schema must be an object")
        return
    schema_type = value.get("type")
    valid_type = isinstance(schema_type, str) and schema_type in _SCHEMA_TYPES
    valid_type = valid_type or (
        isinstance(schema_type, list)
        and bool(schema_type)
        and all(isinstance(item, str) and item in _SCHEMA_TYPES for item in schema_type)
    )
    if schema_type is not None and not valid_type:
        _issue(issues, "invalid_schema_type", f"{path}.type", "type contains an unsupported JSON Schema type")
    properties = value.get("properties")
    if properties is not None:
        if not isinstance(properties, Mapping):
            _issue(issues, "schema_properties_not_object", f"{path}.properties", "properties must be an object")
        else:
            for name, child in properties.items():
                if not isinstance(name, str) or not name:
                    _issue(issues, "invalid_schema_property", f"{path}.properties", "property names must be strings")
                else:
                    _validate_json_schema(child, f"{path}.properties.{name}", issues, depth + 1)
    required = value.get("required")
    if required is not None:
        _validate_string_sequence(required, f"{path}.required", issues)
        if isinstance(required, list) and isinstance(properties, Mapping):
            for name in required:
                if name not in properties:
                    _issue(
                        issues,
                        "schema_required_property_missing",
                        f"{path}.required",
                        f"unknown required property: {name}",
                    )
    items = value.get("items")
    if items is not None:
        if isinstance(items, list):
            _issue(issues, "schema_items_array_unsupported", f"{path}.items", "tuple item schemas are not supported")
        else:
            _validate_json_schema(items, f"{path}.items", issues, depth + 1)
    enum = value.get("enum")
    if enum is not None and (not isinstance(enum, list) or not enum):
        _issue(issues, "invalid_schema_enum", f"{path}.enum", "enum must be a non-empty array")
    ref = value.get("$ref")
    if ref is not None and (not isinstance(ref, str) or not ref.startswith("#")):
        _issue(issues, "external_schema_ref", f"{path}.$ref", "external schema references are not allowed")


def _validate_resource_references(value: Any, path: str, issues: list[dict[str, Any]]) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(key, str) and key in _RESOURCE_KEYS:
                _validate_resource_value(child, child_path, issues)
            elif isinstance(child, (Mapping, list)):
                _validate_resource_references(child, child_path, issues)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _validate_resource_references(child, f"{path}[{index}]", issues)


def _validate_resource_value(value: Any, path: str, issues: list[dict[str, Any]]) -> None:
    refs = [value] if isinstance(value, str) else value if isinstance(value, list) else None
    if refs is None:
        _issue(issues, "invalid_resource_reference", path, "resource reference must be a string or array")
        return
    for index, ref in enumerate(refs):
        ref_path = f"{path}[{index}]" if isinstance(value, list) else path
        if not isinstance(ref, str) or not ref.strip():
            _issue(issues, "invalid_resource_reference", ref_path, "resource reference must be a non-empty string")
            continue
        normalized = ref.replace("\\", "/")
        if _WINDOWS_ABSOLUTE_RE.match(ref) or normalized.startswith("/") or "://" in normalized:
            _issue(issues, "unsafe_resource_reference", ref_path, "absolute paths and URLs are not allowed")
        if any(part == ".." for part in normalized.split("/")):
            _issue(issues, "unsafe_resource_reference", ref_path, "parent traversal is not allowed")


def _validate_string_sequence(value: Any, path: str, issues: list[dict[str, Any]]) -> None:
    if not isinstance(value, list) or any(not isinstance(item, str) or not item.strip() for item in value):
        _issue(issues, "string_array_required", path, "value must be an array of non-empty strings")


def _edge_endpoint(edge: Mapping[str, Any], side: str) -> str | None:
    aliases = {
        "source": ("source_node_key", "source", "from", "source_node_id"),
        "target": ("target_node_key", "target", "to", "target_node_id"),
    }
    for key in aliases[side]:
        value = edge.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _issue(issues: list[dict[str, Any]], code: str, path: str, message: str) -> None:
    issues.append({"code": code, "path": path, "message": message})

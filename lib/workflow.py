"""Shotwise workflow domain primitives.

The module is intentionally independent from FastAPI and SQLAlchemy so the
same validation and fingerprint rules can be used by the API, scheduler and
agent adapters.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections import defaultdict, deque
from typing import Any

from pydantic import BaseModel, Field

RUN_STATUSES = frozenset({"planned", "running", "paused", "waiting_review", "succeeded", "failed", "cancelled"})
TEMPLATE_STATUSES = frozenset({"draft", "submitted", "under_review", "published", "rejected", "suspended"})
CONTENT_MODES = frozenset({"manga", "drama", "narration", "ad"})
GENERATION_MODES = frozenset({"storyboard", "reference_video"})
BUILTIN_NODE_TYPES = frozenset(
    {
        "source_import",
        "script_generate",
        "script_review",
        "character_reference",
        "storyboard_generate",
        "storyboard_review",
        "shot_image_generate",
        "shot_video_generate",
        "voice_generate",
        "subtitle_generate",
        "compose",
        "quality_check",
        "export",
        "image_input",
        "video_input",
        "loop",
        "branch",
        "param_adjust",
    }
)
QUALITY_GATE_IDS = (
    "script_structure_complete",
    "character_references_consistent",
    "scene_references_exist",
    "storyboard_complete",
    "video_duration_legal",
    "subtitles_in_bounds",
    "audio_video_sync",
    "output_files_complete",
)
NODE_STATUSES = frozenset(
    {
        "blocked",
        "ready",
        "queued",
        "running",
        "collecting",
        "succeeded",
        "retry_wait",
        "failed",
        "waiting_review",
        "skipped",
        "stale",
        "orphaned",
        "cancelled",
    }
)
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled"})
TERMINAL_NODE_STATUSES = frozenset({"succeeded", "failed", "skipped", "stale", "orphaned", "cancelled"})

_RUN_TRANSITIONS: dict[str, frozenset[str]] = {
    "planned": frozenset({"running", "cancelled"}),
    "running": frozenset({"paused", "waiting_review", "succeeded", "failed", "cancelled"}),
    "paused": frozenset({"running", "cancelled"}),
    "waiting_review": frozenset({"running", "cancelled"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "cancelled": frozenset(),
}

_NODE_TRANSITIONS: dict[str, frozenset[str]] = {
    "blocked": frozenset({"ready", "skipped", "cancelled"}),
    "ready": frozenset({"queued", "waiting_review", "cancelled", "stale"}),
    "queued": frozenset({"running", "retry_wait", "failed", "cancelled", "orphaned"}),
    "running": frozenset({"collecting", "retry_wait", "failed", "cancelled", "orphaned"}),
    "collecting": frozenset({"succeeded", "retry_wait", "failed", "cancelled", "orphaned"}),
    "retry_wait": frozenset({"ready", "cancelled", "failed"}),
    "waiting_review": frozenset({"ready", "cancelled", "stale"}),
    "succeeded": frozenset(),
    "failed": frozenset(),
    "skipped": frozenset(),
    "stale": frozenset(),
    "orphaned": frozenset(),
    "cancelled": frozenset(),
}


class WorkflowValidationError(ValueError):
    """Raised when a workflow revision cannot be published."""

    def __init__(self, code: str, **params: Any) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


class WorkflowPatchOperation(BaseModel):
    """One safe, auditable graph/config change proposed by the agent."""

    operation: str = Field(pattern=r"^(set_config|add_node|remove_node|add_edge|remove_edge)$")
    target_node: str | None = None
    path: str | None = None
    before: Any = None
    after: Any = None
    estimated_cost_delta: float = 0.0
    requires_confirmation: bool = False


class WorkflowPatch(BaseModel):
    base_revision_id: str
    operations: list[WorkflowPatchOperation] = Field(min_length=1, max_length=100)
    scope: str = Field(default="episode", pattern=r"^(shot|scene|episode)$")
    rerun: bool = False
    reason: str = ""


def _set_path(value: dict[str, Any], path: str, new_value: Any) -> None:
    parts = [part for part in path.split(".") if part]
    if not parts:
        raise WorkflowValidationError("workflow_patch_invalid", reason="path")
    cursor = value
    for part in parts[:-1]:
        child = cursor.get(part)
        if not isinstance(child, dict):
            child = {}
            cursor[part] = child
        cursor = child
    cursor[parts[-1]] = new_value


def apply_patch_to_graph(
    nodes: list[dict[str, Any]], edges: list[dict[str, Any]], patch: WorkflowPatch
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Apply a validated patch to a detached graph copy.

    Published rows are never mutated. The caller persists the returned graph as
    a new draft revision after authorization.
    """
    next_nodes = [json.loads(canonical_json(node)) for node in nodes]
    next_edges = [json.loads(canonical_json(edge)) for edge in edges]
    node_by_key = {str(node["node_key"]): node for node in next_nodes}
    for operation in patch.operations:
        if operation.operation == "set_config":
            if not operation.target_node or operation.target_node not in node_by_key:
                raise WorkflowValidationError("workflow_patch_invalid", reason="unknown_node")
            path = operation.path or ""
            config = node_by_key[operation.target_node].setdefault("config", {})
            if not isinstance(config, dict):
                raise WorkflowValidationError("workflow_patch_invalid", reason="config")
            _set_path(config, path, operation.after)
        elif operation.operation == "add_node":
            candidate = operation.after
            if not isinstance(candidate, dict) or not candidate.get("node_key"):
                raise WorkflowValidationError("workflow_patch_invalid", reason="node_payload")
            key = str(candidate["node_key"])
            if key in node_by_key:
                raise WorkflowValidationError("workflow_input_invalid", reason="node_key")
            node_by_key[key] = json.loads(canonical_json(candidate))
            next_nodes.append(node_by_key[key])
        elif operation.operation == "remove_node":
            key = str(operation.target_node or "")
            if key not in node_by_key:
                raise WorkflowValidationError("workflow_patch_invalid", reason="unknown_node")
            next_nodes = [node for node in next_nodes if str(node["node_key"]) != key]
            node_by_key.pop(key, None)
            next_edges = [
                edge for edge in next_edges if edge.get("source_node_key") != key and edge.get("target_node_key") != key
            ]
        elif operation.operation == "add_edge":
            candidate = operation.after
            if not isinstance(candidate, dict):
                raise WorkflowValidationError("workflow_patch_invalid", reason="edge_payload")
            next_edges.append(json.loads(canonical_json(candidate)))
        elif operation.operation == "remove_edge":
            edge_key = str(operation.target_node or operation.path or "")
            next_edges = [edge for edge in next_edges if str(edge.get("edge_key")) != edge_key]
    validate_graph(next_nodes, next_edges)
    validate_node_contracts(next_nodes)
    return next_nodes, next_edges


def template_transition(status: str, target: str) -> None:
    transitions = {
        "draft": {"submitted"},
        "submitted": {"draft", "under_review"},
        "under_review": {"published", "rejected", "draft"},
        "published": {"suspended"},
        "rejected": {"draft", "submitted"},
        "suspended": {"published"},
    }
    if status not in TEMPLATE_STATUSES or target not in transitions.get(status, set()):
        raise WorkflowValidationError("workflow_template_invalid_transition", status=status, target=target)


def validate_modes(content_mode: str, generation_mode: str) -> None:
    if content_mode not in CONTENT_MODES:
        raise WorkflowValidationError("workflow_input_invalid", reason="content_mode")
    if generation_mode not in GENERATION_MODES:
        raise WorkflowValidationError("workflow_input_invalid", reason="generation_mode")


def validate_node_contracts(nodes: list[dict[str, Any]]) -> None:
    """Accept only reviewed built-in runtime nodes during the initial release."""
    for node in nodes:
        node_type = str(node.get("node_type", ""))
        executor_id = str(node.get("executor_id", "builtin"))
        cache_policy = str(node.get("cache_policy", "reuse"))
        if node_type not in BUILTIN_NODE_TYPES:
            raise WorkflowValidationError("workflow_node_not_allowed", node_type=node_type)
        if executor_id != "builtin":
            raise WorkflowValidationError("workflow_executor_not_allowed", executor_id=executor_id)
        if cache_policy not in {"reuse", "refresh", "never"}:
            raise WorkflowValidationError("workflow_input_invalid", reason="cache_policy")
        if float(node.get("estimated_cost", 0)) < 0:
            raise WorkflowValidationError("workflow_input_invalid", reason="estimated_cost")


def quality_gate_report(facts: dict[str, bool | dict[str, Any]], required: list[str] | None = None) -> dict[str, Any]:
    """Normalize quality-gate facts into a pause-able, actionable report."""
    checks = required or list(QUALITY_GATE_IDS)
    failures: list[dict[str, Any]] = []
    results: dict[str, dict[str, Any]] = {}
    for gate_id in checks:
        raw = facts.get(gate_id, False)
        if isinstance(raw, dict):
            passed = bool(raw.get("ok", False))
            message = str(raw.get("message") or gate_id)
            suggestion = str(raw.get("suggestion") or "检查该门禁所需的输入和上游产物")
        else:
            passed = bool(raw)
            message = gate_id
            suggestion = "检查该门禁所需的输入和上游产物"
        results[gate_id] = {"passed": passed, "message": message, "suggestion": suggestion}
        if not passed:
            failures.append({"gate": gate_id, "message": message, "suggestion": suggestion})
    return {"passed": not failures, "results": results, "failures": failures}


def affected_nodes(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], patch: WorkflowPatch) -> set[str]:
    """Return the changed nodes plus their downstream closure for partial execution."""
    validate_graph(nodes, edges)
    outgoing, _ = node_graph_edges(edges)
    changed = {op.target_node for op in patch.operations if op.target_node}
    changed.discard(None)
    result = set(changed)
    queue = deque(changed)
    while queue:
        key = queue.popleft()
        for target in outgoing.get(str(key), set()):
            if target not in result:
                result.add(target)
                queue.append(target)
    return {str(value) for value in result}


def validate_patch(
    nodes: list[dict[str, Any]],
    edges: list[dict[str, Any]],
    patch: WorkflowPatch,
    *,
    remaining_budget: float | None = None,
    allow_destructive: bool = False,
) -> dict[str, Any]:
    """Validate an agent patch without mutating a published revision."""
    validate_graph(nodes, edges)
    keys = {str(node["node_key"]) for node in nodes}
    total_delta = sum(float(op.estimated_cost_delta) for op in patch.operations)
    for op in patch.operations:
        if op.operation == "set_config" and not op.target_node:
            raise WorkflowValidationError("workflow_patch_invalid", reason="target_node")
        if op.target_node and op.target_node not in keys and op.operation not in {"add_node"}:
            raise WorkflowValidationError("workflow_patch_invalid", reason="unknown_node", node_key=op.target_node)
        if op.operation in {"remove_node", "remove_edge"} and not allow_destructive:
            raise WorkflowValidationError("workflow_patch_confirmation_required", operation=op.operation)
    if remaining_budget is not None and total_delta > remaining_budget:
        raise WorkflowValidationError(
            "workflow_budget_exceeded", estimated_delta=total_delta, remaining=remaining_budget
        )
    return {
        "valid": True,
        "affected_nodes": sorted(affected_nodes(nodes, edges, patch)),
        "estimated_cost_delta": total_delta,
        "requires_confirmation": any(op.requires_confirmation for op in patch.operations),
    }


def canonical_json(value: Any) -> str:
    """Serialize JSON deterministically for hashes and idempotency checks."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def normalize_prompt(value: str) -> str:
    """Apply only the prompt normalization allowed by the architecture spec."""

    normalized = unicodedata.normalize("NFC", value.replace("\r\n", "\n").replace("\r", "\n"))
    return normalized.rstrip("\n")


def input_fingerprint(payload: dict[str, Any]) -> str:
    """Return a SHA-256 fingerprint of a canonical generation input snapshot."""

    normalized = dict(payload)
    for key in ("prompt", "negative_prompt", "canonical_prompt"):
        if isinstance(normalized.get(key), str):
            normalized[key] = normalize_prompt(normalized[key])
    return hashlib.sha256(canonical_json(normalized).encode("utf-8")).hexdigest()


def graph_hash(nodes: list[dict[str, Any]], edges: list[dict[str, Any]], *, include_layout: bool) -> str:
    """Hash a graph, optionally excluding UI-only node positions."""

    node_values = []
    for node in nodes:
        item = dict(node)
        if not include_layout:
            item.pop("ui_position", None)
            item.pop("ui_position_json", None)
        node_values.append(item)
    value = {
        "nodes": sorted(node_values, key=lambda x: str(x.get("node_key", ""))),
        "edges": sorted(edges, key=lambda x: str(x.get("edge_key", ""))),
    }
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_graph(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
    """Validate node identity, references, reachability and cycles."""

    node_keys = [str(node.get("node_key", "")) for node in nodes]
    if not node_keys or any(not key for key in node_keys) or len(node_keys) != len(set(node_keys)):
        raise WorkflowValidationError("workflow_input_invalid", reason="node_key")

    known = set(node_keys)
    edge_keys = [str(edge["edge_key"]) for edge in edges if edge.get("edge_key")]
    if len(edge_keys) != len(set(edge_keys)):
        raise WorkflowValidationError("workflow_input_invalid", reason="edge_key")
    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge.get("source_node_key", ""))
        target = str(edge.get("target_node_key", ""))
        if not source or not target or source not in known or target not in known:
            raise WorkflowValidationError("workflow_input_invalid", reason="edge_reference")
        if source == target:
            raise WorkflowValidationError("workflow_cycle_detected", node_key=source)
        outgoing[source].add(target)
        incoming[target].add(source)

    roots = [key for key in node_keys if not incoming[key]]
    if not roots:
        raise WorkflowValidationError("workflow_cycle_detected")
    visited: set[str] = set()
    queue = deque(roots)
    while queue:
        key = queue.popleft()
        if key in visited:
            continue
        visited.add(key)
        queue.extend(outgoing[key])
    if len(visited) != len(known):
        raise WorkflowValidationError("workflow_input_invalid", reason="unreachable_node")

    indegree = {key: len(incoming[key]) for key in node_keys}
    queue = deque(key for key, degree in indegree.items() if degree == 0)
    processed = 0
    while queue:
        key = queue.popleft()
        processed += 1
        for target in outgoing[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if processed != len(known):
        raise WorkflowValidationError("workflow_cycle_detected")


def transition_run(status: str, target: str) -> None:
    if status not in RUN_STATUSES or target not in RUN_STATUSES or target not in _RUN_TRANSITIONS[status]:
        raise WorkflowValidationError("workflow_invalid_transition", entity="run", status=status, target=target)


def transition_node(status: str, target: str) -> None:
    if status not in NODE_STATUSES or target not in NODE_STATUSES or target not in _NODE_TRANSITIONS[status]:
        raise WorkflowValidationError("workflow_invalid_transition", entity="node", status=status, target=target)


def node_graph_edges(edges: list[dict[str, Any]]) -> tuple[dict[str, set[str]], dict[str, set[str]]]:
    """Build outgoing/incoming adjacency maps from edge dicts.

    The maps are keyed by node_key; node keys are stringified exactly like
    ``validate_graph`` does so the execution engine and validators agree.
    """

    outgoing: dict[str, set[str]] = defaultdict(set)
    incoming: dict[str, set[str]] = defaultdict(set)
    for edge in edges:
        source = str(edge.get("source_node_key", ""))
        target = str(edge.get("target_node_key", ""))
        if not source or not target:
            continue
        outgoing[source].add(target)
        incoming[target].add(source)
    return outgoing, incoming


def topological_order(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> list[str]:
    """Return node keys in dependency order (roots first) via Kahn's algorithm.

    Raises :class:`WorkflowValidationError` with ``workflow_cycle_detected`` on
    cycles, matching ``validate_graph``. Keys are deduplicated against the
    ``node_key`` field of ``nodes``.
    """

    validate_graph(nodes, edges)
    outgoing, _incoming = node_graph_edges(edges)
    indegree = {str(node["node_key"]): 0 for node in nodes}
    for source, targets in outgoing.items():
        for target in targets:
            if target in indegree:
                indegree[target] += 1
    queue = deque(key for key, degree in indegree.items() if degree == 0)
    ordered: list[str] = []
    while queue:
        key = queue.popleft()
        ordered.append(key)
        for target in outgoing[key]:
            indegree[target] -= 1
            if indegree[target] == 0:
                queue.append(target)
    if len(ordered) != len(indegree):
        raise WorkflowValidationError("workflow_cycle_detected")
    return ordered


def upstream_of(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, set[str]]:
    """Return for each node_key the set of keys that can reach it (transitively)."""

    _outgoing, incoming = node_graph_edges(edges)
    result: dict[str, set[str]] = {str(node["node_key"]): set() for node in nodes}
    order = topological_order(nodes, edges)
    for key in order:
        seen: set[str] = set()
        for source in incoming[key]:
            seen.add(source)
            seen.update(result[source])
        result[key] = seen
    return result

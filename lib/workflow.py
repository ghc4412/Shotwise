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

RUN_STATUSES = frozenset({"planned", "running", "paused", "waiting_review", "succeeded", "failed", "cancelled"})
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

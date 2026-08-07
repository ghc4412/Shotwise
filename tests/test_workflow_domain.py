from __future__ import annotations

import pytest

from lib.workflow import WorkflowValidationError, graph_hash, input_fingerprint, transition_run, validate_graph

pytestmark = pytest.mark.unit


def test_input_fingerprint_normalizes_only_unicode_and_line_endings() -> None:
    left = input_fingerprint({"prompt": "Cafe\u0301\r\nwide  shot\n", "seed": 7})
    right = input_fingerprint({"prompt": "Caf\u00e9\nwide  shot", "seed": 7})
    changed = input_fingerprint({"prompt": "caf\u00e9\nwide shot", "seed": 7})

    assert left == right
    assert changed != right


def test_execution_hash_ignores_layout_but_graph_hash_tracks_it() -> None:
    edges: list[dict] = []
    left = [{"node_key": "source", "node_type": "source_import", "ui_position": {"x": 0, "y": 0}}]
    right = [{"node_key": "source", "node_type": "source_import", "ui_position": {"x": 40, "y": 20}}]

    assert graph_hash(left, edges, include_layout=False) == graph_hash(right, edges, include_layout=False)
    assert graph_hash(left, edges, include_layout=True) != graph_hash(right, edges, include_layout=True)


def test_validate_graph_accepts_parallel_dag() -> None:
    nodes = [{"node_key": key} for key in ("source", "image", "voice", "compose")]
    edges = [
        {"source_node_key": "source", "target_node_key": "image"},
        {"source_node_key": "source", "target_node_key": "voice"},
        {"source_node_key": "image", "target_node_key": "compose"},
        {"source_node_key": "voice", "target_node_key": "compose"},
    ]

    validate_graph(nodes, edges)


@pytest.mark.parametrize(
    "nodes,edges,code",
    [
        (
            [{"node_key": "a"}, {"node_key": "b"}],
            [
                {"source_node_key": "a", "target_node_key": "b"},
                {"source_node_key": "b", "target_node_key": "a"},
            ],
            "workflow_cycle_detected",
        ),
        (
            [{"node_key": "a"}, {"node_key": "b"}],
            [{"source_node_key": "missing", "target_node_key": "b"}],
            "workflow_input_invalid",
        ),
    ],
)
def test_validate_graph_rejects_invalid_graph(nodes: list[dict], edges: list[dict], code: str) -> None:
    with pytest.raises(WorkflowValidationError, match=code):
        validate_graph(nodes, edges)


def test_terminal_run_cannot_transition() -> None:
    with pytest.raises(WorkflowValidationError, match="workflow_invalid_transition"):
        transition_run("cancelled", "running")

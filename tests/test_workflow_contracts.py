from __future__ import annotations

import pytest

from server.services.workflow_contracts import WorkflowContractValidationError, validate_workflow_template_contract

pytestmark = pytest.mark.unit


def test_validates_node_schemas_and_graph() -> None:
    result = validate_workflow_template_contract(
        {
            "input_schema": {"type": "object", "properties": {"episode": {"type": "integer"}}},
            "nodes": [
                {
                    "node_key": "script",
                    "executor_id": "script.parse",
                    "input_schema": {
                        "type": "object",
                        "required": ["episode"],
                        "properties": {"episode": {"type": "integer"}},
                    },
                    "output_schema": {"type": "object"},
                    "required_capabilities": ["text"],
                    "estimated_cost": 0,
                    "resource_refs": ["assets/script.json"],
                },
                {"node_key": "render", "executor_id": "video.render", "input_schema": {"type": "object"}},
            ],
            "edges": [{"source_node_key": "script", "target_node_key": "render"}],
        },
        allowed_executor_ids={"script.parse", "video.render"},
        available_capabilities={"text"},
    )
    assert result == {"valid": True, "node_count": 2, "edge_count": 1, "missing_endpoints": []}


@pytest.mark.parametrize(
    ("contract", "code"),
    [
        ({"nodes": [{"node_key": "a"}, {"node_key": "a"}]}, "duplicate_node_id"),
        (
            {
                "nodes": [{"node_key": "a"}, {"node_key": "b"}],
                "edges": [{"source_node_key": "a", "target_node_key": "missing"}],
            },
            "missing_edge_endpoint",
        ),
        (
            {
                "nodes": [{"node_key": "a"}, {"node_key": "b"}],
                "edges": [
                    {"source_node_key": "a", "target_node_key": "b"},
                    {"source_node_key": "b", "target_node_key": "a"},
                ],
            },
            "workflow_cycle_detected",
        ),
        ({"nodes": [{"node_key": "a", "input_schema": {"type": "wat"}}]}, "invalid_schema_type"),
        ({"nodes": [{"node_key": "a", "resource_ref": "../private.txt"}]}, "unsafe_resource_reference"),
    ],
)
def test_rejects_unsafe_or_invalid_contracts(contract: dict[str, object], code: str) -> None:
    with pytest.raises(WorkflowContractValidationError) as exc_info:
        validate_workflow_template_contract(contract)
    assert code in {issue["code"] for issue in exc_info.value.issues}


def test_enforces_executor_and_capability_allowlists() -> None:
    with pytest.raises(WorkflowContractValidationError) as exc_info:
        validate_workflow_template_contract(
            {
                "nodes": [
                    {
                        "node_key": "render",
                        "executor_id": "untrusted.exec",
                        "required_capabilities": ["secret-provider"],
                    }
                ]
            },
            allowed_executor_ids={"video.render"},
            available_capabilities={"text"},
        )
    codes = {issue["code"] for issue in exc_info.value.issues}
    assert {"unknown_executor_id", "capability_unavailable"} <= codes

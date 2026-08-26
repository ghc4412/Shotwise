"""Persistence-level invariants for workflow core tables."""

import pytest
from sqlalchemy import UniqueConstraint

from lib.db.models.workflow import WorkflowDefinition, WorkflowEdge, WorkflowNode, WorkflowRevision, WorkflowRun


def _constraint_names(table: object) -> set[str]:
    return {constraint.name for constraint in table.constraints if constraint.name}


@pytest.mark.unit
def test_workflow_core_tables_are_modelled() -> None:
    assert {
        "workflow_definitions",
        "workflow_revisions",
        "workflow_nodes",
        "workflow_edges",
        "workflow_runs",
        "workflow_node_runs",
        "workflow_templates",
        "workflow_marketplace_reviews",
        "workflow_usage_stats",
    } <= {table.name for table in WorkflowDefinition.metadata.tables.values()}


@pytest.mark.unit
def test_revision_identity_and_modes_have_database_constraints() -> None:
    constraints = _constraint_names(WorkflowRevision.__table__)
    assert "uq_workflow_revision_number" in constraints
    assert "ck_workflow_revision_number_positive" in constraints
    assert "ck_workflow_revision_content_mode" in constraints
    assert "ck_workflow_revision_generation_mode" in constraints
    assert "ck_workflow_revision_graph_hash_nonempty" in constraints
    assert "ck_workflow_revision_execution_hash_nonempty" in constraints
    assert WorkflowRevision.__table__.c.graph_hash.nullable is False
    assert WorkflowRevision.__table__.c.execution_hash.nullable is False


@pytest.mark.unit
def test_node_identity_and_run_budget_have_database_constraints() -> None:
    node_constraints = _constraint_names(WorkflowNode.__table__)
    run_constraints = _constraint_names(WorkflowRun.__table__)
    assert "uq_workflow_node_key" in node_constraints
    assert "ck_workflow_node_weight_nonnegative" in node_constraints
    assert "ck_workflow_node_estimated_cost_nonnegative" in node_constraints
    assert "ck_workflow_run_budget_limit_nonnegative" in run_constraints
    assert "ck_workflow_run_spent_nonnegative" in run_constraints
    assert "ck_workflow_run_reserved_nonnegative" in run_constraints
    assert "ck_workflow_run_budget_not_exceeded" in run_constraints


@pytest.mark.unit
def test_edges_keep_revision_scoped_identity() -> None:
    unique_constraints = {
        constraint.name for constraint in WorkflowEdge.__table__.constraints if isinstance(constraint, UniqueConstraint)
    }
    assert "uq_workflow_edge_key" in unique_constraints

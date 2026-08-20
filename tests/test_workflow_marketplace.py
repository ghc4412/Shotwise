from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.api_errors import ConflictError
from lib.db.models.user import User
from lib.workflow import (
    WorkflowPatch,
    WorkflowValidationError,
    affected_nodes,
    quality_gate_report,
    template_transition,
    validate_patch,
)
from server.services import workflows

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _seed_users(async_session) -> None:
    if async_session.get_bind().dialect.name == "sqlite":
        await async_session.execute(text("PRAGMA foreign_keys=ON"))
    for user_id in ("default", "creator"):
        if await async_session.get(User, user_id) is None:
            async_session.add(
                User(id=user_id, username=f"wf-market-{user_id}", role="admin" if user_id == "default" else "user")
            )
    await async_session.flush()


def _graph() -> tuple[list[dict], list[dict]]:
    nodes = [
        {"node_key": "source", "node_type": "source_import", "estimated_cost": 0},
        {"node_key": "render", "node_type": "shot_image_generate", "estimated_cost": 3.5},
        {"node_key": "export", "node_type": "export", "estimated_cost": 0},
    ]
    edges = [
        {"edge_key": "source-render", "source_node_key": "source", "target_node_key": "render"},
        {"edge_key": "render-export", "source_node_key": "render", "target_node_key": "export"},
    ]
    return nodes, edges


def test_template_transition_is_closed() -> None:
    template_transition("draft", "submitted")
    with pytest.raises(WorkflowValidationError, match="workflow_template_invalid_transition"):
        template_transition("published", "draft")


def test_patch_validation_returns_downstream_closure_and_rejects_budget_overrun() -> None:
    nodes, edges = _graph()
    patch = WorkflowPatch(
        base_revision_id="rev",
        operations=[{"operation": "set_config", "target_node": "render", "estimated_cost_delta": 2}],
    )
    assert affected_nodes(nodes, edges, patch) == {"render", "export"}
    assert validate_patch(nodes, edges, patch, remaining_budget=2)["affected_nodes"] == ["export", "render"]
    with pytest.raises(WorkflowValidationError, match="workflow_budget_exceeded"):
        validate_patch(nodes, edges, patch, remaining_budget=1)


async def test_template_submission_review_publish_and_derivation(async_session) -> None:
    nodes, edges = _graph()
    draft = await workflows.create_template_draft(
        async_session,
        name="Rainy night manga",
        description="A reviewed manga pipeline",
        template_type="manga",
        contract={"input_schema": {"type": "object"}},
        nodes=nodes,
        edges=edges,
        actor_id="creator",
        content_mode="manga",
    )
    await workflows.submit_template(async_session, draft["id"], actor_id="creator")
    await workflows.review_template(
        async_session,
        draft["id"],
        reviewer_id="default",
        decision="approve",
        comment="Static validation passed",
    )
    published = await workflows.get_template(async_session, draft["id"], actor_id="creator")
    assert published["status"] == "published"
    assert published["revision"]["content_mode"] == "manga"
    derived = await workflows.derive_template(
        async_session,
        draft["id"],
        workspace_id="default",
        project_id="project-1",
        name="Private copy",
        actor_id="creator",
    )
    graph = await workflows.get_workflow(async_session, derived["definition_id"], actor_id="creator")
    assert graph["active_revision"]["template_lock"]["template_id"] == draft["id"]


async def test_template_cannot_be_derived_after_suspension(async_session) -> None:
    nodes, edges = _graph()
    draft = await workflows.create_template_draft(
        async_session,
        name="Short drama",
        description="",
        template_type="short_drama",
        contract={},
        nodes=nodes,
        edges=edges,
        actor_id="creator",
    )
    await workflows.submit_template(async_session, draft["id"], actor_id="creator")
    await workflows.review_template(async_session, draft["id"], reviewer_id="default", decision="approve", comment="ok")
    await workflows.set_template_suspended(async_session, draft["id"], reviewer_id="default", suspended=True)
    with pytest.raises(ConflictError, match="workflow_template_not_published"):
        await workflows.derive_template(
            async_session,
            draft["id"],
            workspace_id="default",
            project_id="project-1",
            name="copy",
            actor_id="creator",
        )


async def test_episode_budget_is_exposed_on_run(async_session) -> None:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="budget", name="budget", actor_id="creator"
    )
    nodes, edges = _graph()
    revision = await workflows.create_revision(
        async_session,
        definition_id=definition["id"],
        nodes=nodes,
        edges=edges,
        template_lock=None,
        actor_id="creator",
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="creator")
    run = await workflows.plan_run(
        async_session,
        revision_id=revision["id"],
        workspace_id="default",
        project_id="budget",
        mode="hybrid",
        input_snapshot={},
        script_revision_id=None,
        actor_id="creator",
        episode_id="episode-3",
        budget_limit=10,
    )
    detail = await workflows.get_run(async_session, run["id"], actor_id="creator")
    assert detail["episode_id"] == "episode-3"
    assert detail["remaining_amount"] == 10


async def test_confirmed_patch_creates_new_revision_and_can_start(async_session) -> None:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="patch", name="patch", actor_id="creator"
    )
    nodes, edges = _graph()
    revision = await workflows.create_revision(
        async_session,
        definition_id=definition["id"],
        nodes=nodes,
        edges=edges,
        template_lock=None,
        actor_id="creator",
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="creator")
    run = await workflows.plan_run(
        async_session,
        revision_id=revision["id"],
        workspace_id="default",
        project_id="patch",
        mode="hybrid",
        input_snapshot={"episode": 1},
        script_revision_id=None,
        actor_id="creator",
        episode_id="1",
        budget_limit=20,
    )
    patch = WorkflowPatch(
        base_revision_id=revision["id"],
        operations=[
            {
                "operation": "set_config",
                "target_node": "render",
                "path": "style",
                "after": "rainy-night",
                "requires_confirmation": False,
            }
        ],
        reason="Change episode weather",
    )
    applied = await workflows.apply_patch_for_run(
        async_session, run["id"], patch, actor_id="creator", confirmed=True, start=False
    )
    assert applied["status"] == "draft"
    graph = await workflows.get_workflow(async_session, definition["id"], actor_id="creator")
    assert graph["active_revision"]["id"] == revision["id"]
    revisions = await workflows.list_revisions(async_session, definition["id"], actor_id="creator")
    assert revisions["items"][0]["id"] == applied["revision_id"]


def test_quality_gate_report_contains_actionable_failures() -> None:
    report = quality_gate_report(
        {"script_structure_complete": {"ok": False, "message": "missing scenes", "suggestion": "add scenes"}},
        required=["script_structure_complete"],
    )
    assert report["passed"] is False
    assert report["failures"] == [
        {"gate": "script_structure_complete", "message": "missing scenes", "suggestion": "add scenes"}
    ]

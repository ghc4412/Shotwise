from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.api_errors import ConflictError, NotFoundError
from lib.db.models.user import User
from server.services import workflows

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _enable_sqlite_foreign_keys(async_session) -> None:
    if async_session.get_bind().dialect.name == "sqlite":
        await async_session.execute(text("PRAGMA foreign_keys=ON"))
    async_session.add(User(id="default", username="workflow-test-default"))
    async_session.add(User(id="intruder", username="workflow-test-intruder"))
    await async_session.flush()


def _nodes() -> list[dict]:
    return [
        {"node_key": "source", "node_type": "source_import", "weight": 1},
        {"node_key": "storyboard", "node_type": "storyboard_generate", "weight": 3},
        {"node_key": "export", "node_type": "export", "weight": 1},
    ]


def _edges() -> list[dict]:
    return [
        {"edge_key": "source-storyboard", "source_node_key": "source", "target_node_key": "storyboard"},
        {"edge_key": "storyboard-export", "source_node_key": "storyboard", "target_node_key": "export"},
    ]


async def _published_revision(async_session) -> tuple[str, str]:
    definition = await workflows.create_definition(
        async_session,
        workspace_id="default",
        project_id="demo",
        name="Demo production",
        actor_id="default",
    )
    revision = await workflows.create_revision(
        async_session,
        definition_id=definition["id"],
        nodes=_nodes(),
        edges=_edges(),
        template_lock={"template_schema_version": 1},
        actor_id="default",
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="default")
    return definition["id"], revision["id"]


async def test_publish_revision_and_plan_materializes_root_nodes(async_session) -> None:
    definition_id, revision_id = await _published_revision(async_session)

    graph = await workflows.get_workflow(async_session, definition_id, actor_id="default")
    planned = await workflows.plan_run(
        async_session,
        revision_id=revision_id,
        workspace_id="default",
        project_id="demo",
        mode="hybrid",
        input_snapshot={"prompt": "three shots"},
        script_revision_id="script-v1",
        actor_id="default",
    )
    run = await workflows.get_run(async_session, planned["id"], actor_id="default")

    assert graph["active_revision"]["status"] == "published"
    assert run["status"] == "planned"
    assert {node["node_key"]: node["status"] for node in run["nodes"]} == {
        "source": "ready",
        "storyboard": "blocked",
        "export": "blocked",
    }


async def test_plan_run_deduplicates_active_input(async_session) -> None:
    _, revision_id = await _published_revision(async_session)
    values = {
        "revision_id": revision_id,
        "workspace_id": "default",
        "project_id": "demo",
        "mode": "hybrid",
        "input_snapshot": {"prompt": "same input"},
        "script_revision_id": None,
        "actor_id": "default",
    }

    first = await workflows.plan_run(async_session, **values)
    second = await workflows.plan_run(async_session, **values)

    assert first["id"] == second["id"]
    assert first["deduped"] is False
    assert second["deduped"] is True


async def test_run_transition_uses_version_and_writes_replayable_events(async_session) -> None:
    _, revision_id = await _published_revision(async_session)
    planned = await workflows.plan_run(
        async_session,
        revision_id=revision_id,
        workspace_id="default",
        project_id="demo",
        mode="manual",
        input_snapshot={},
        script_revision_id=None,
        actor_id="default",
    )

    started = await workflows.transition_workflow_run(
        async_session,
        run_id=planned["id"],
        target="running",
        expected_version=1,
        actor_id="default",
    )
    with pytest.raises(ConflictError):
        await workflows.transition_workflow_run(
            async_session,
            run_id=planned["id"],
            target="paused",
            expected_version=1,
            actor_id="default",
        )
    paused = await workflows.transition_workflow_run(
        async_session,
        run_id=planned["id"],
        target="paused",
        expected_version=started["version"],
        actor_id="default",
    )
    events = await workflows.list_events(async_session, "demo", actor_id="default")

    assert paused["control_generation"] == 1
    assert events["cursor"] >= 1
    assert any(item["event_type"] == "workflow.run.paused" for item in events["items"])


async def test_workflow_resources_are_isolated_by_user(async_session) -> None:
    definition_id, revision_id = await _published_revision(async_session)
    planned = await workflows.plan_run(
        async_session,
        revision_id=revision_id,
        workspace_id="default",
        project_id="demo",
        mode="hybrid",
        input_snapshot={},
        script_revision_id=None,
        actor_id="default",
    )

    with pytest.raises(NotFoundError):
        await workflows.get_workflow(async_session, definition_id, actor_id="intruder")
    with pytest.raises(NotFoundError):
        await workflows.get_run(async_session, planned["id"], actor_id="intruder")
    with pytest.raises(NotFoundError):
        await workflows.transition_workflow_run(
            async_session,
            run_id=planned["id"],
            target="running",
            expected_version=1,
            actor_id="intruder",
        )

    assert (await workflows.list_runs(async_session, "demo", actor_id="intruder"))["items"] == []
    assert (await workflows.list_events(async_session, "demo", actor_id="intruder"))["items"] == []

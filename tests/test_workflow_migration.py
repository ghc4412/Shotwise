"""Canvas workflow management: migration, export/import, node logs."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.db.models.user import User
from server.services import workflows

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _seed_user(async_session) -> None:
    if async_session.get_bind().dialect.name == "sqlite":
        await async_session.execute(text("PRAGMA foreign_keys=ON"))
    for user_id in ("default", "intruder"):
        if await async_session.get(User, user_id) is None:
            async_session.add(User(id=user_id, username=f"wf-migration-{user_id}"))
    await async_session.flush()


def _graph() -> tuple[list[dict], list[dict]]:
    nodes = [
        {"node_key": "source", "node_type": "source_import", "config": {"source_file": "source/novel.txt"}},
        {"node_key": "script", "node_type": "script_generate", "config": {"episode": 1}},
        {"node_key": "export", "node_type": "export", "config": {}},
    ]
    edges = [
        {"edge_key": "source-script", "source_node_key": "source", "target_node_key": "script"},
        {"edge_key": "script-export", "source_node_key": "script", "target_node_key": "export"},
    ]
    return nodes, edges


async def test_migrate_creates_legacy_linear_chain_once(async_session) -> None:
    first = await workflows.migrate_project(
        async_session, workspace_id="default", project_id="demo", actor_id="default"
    )

    assert first["migrated"] is True
    second = await workflows.migrate_project(
        async_session, workspace_id="default", project_id="demo", actor_id="default"
    )

    assert second["migrated"] is False
    assert second["definition_id"] == first["definition_id"]
    graph = await workflows.get_workflow(async_session, first["definition_id"], actor_id="default")
    nodes = graph["active_revision"]["nodes"]
    assert [node["node_key"] for node in nodes] == workflows.LEGACY_FLOW_NODE_TYPES
    edges = graph["active_revision"]["edges"]
    assert len(edges) == len(workflows.LEGACY_FLOW_NODE_TYPES) - 1


async def test_export_import_roundtrip_preserves_graph(async_session) -> None:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="demo", name="roundtrip", actor_id="default"
    )
    nodes, edges = _graph()
    revision = await workflows.create_revision(
        async_session, definition_id=definition["id"], nodes=nodes, edges=edges, template_lock=None, actor_id="default"
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="default")

    exported = await workflows.export_definition(async_session, definition["id"], actor_id="default")

    assert exported["name"] == "roundtrip"
    assert {node["node_key"] for node in exported["nodes"]} == {"source", "script", "export"}
    imported = await workflows.import_definition(
        async_session,
        workspace_id="default",
        project_id="demo",
        name="imported",
        nodes=exported["nodes"],
        edges=exported["edges"],
        template_lock=exported["template_lock"],
        actor_id="default",
    )
    imported_graph = await workflows.get_workflow(async_session, imported["definition_id"], actor_id="default")
    assert [node["node_key"] for node in imported_graph["active_revision"]["nodes"]] == ["source", "script", "export"]


async def test_export_is_scoped_to_owner(async_session) -> None:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="demo", name="private", actor_id="default"
    )
    with pytest.raises(Exception, match="workflow_not_found"):
        await workflows.export_definition(async_session, definition["id"], actor_id="intruder")


async def test_list_node_logs_filters_by_node_key(async_session) -> None:
    import uuid

    from lib.db.base import utc_now
    from lib.db.models.workflow import ProjectEventLog
    from lib.workflow import canonical_json

    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="demo", name="logs", actor_id="default"
    )
    revision = await workflows.create_revision(
        async_session,
        definition_id=definition["id"],
        nodes=[{"node_key": "script", "node_type": "script_generate", "config": {}}],
        edges=[],
        template_lock=None,
        actor_id="default",
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="default")
    run = await workflows.plan_run(
        async_session,
        revision_id=revision["id"],
        workspace_id="default",
        project_id="demo",
        mode="hybrid",
        input_snapshot={},
        script_revision_id=None,
        actor_id="default",
    )
    for node_key, line in (("script", "line-a"), ("script", "line-b"), ("export", "line-c")):
        async_session.add(
            ProjectEventLog(
                event_id=uuid.uuid4().hex,
                workspace_id="default",
                project_id="demo",
                aggregate_type="workflow_run",
                aggregate_id=run["id"],
                aggregate_version=1,
                event_type="workflow.node_log",
                event_version=1,
                payload_json=canonical_json({"node_key": node_key, "level": "info", "line": line}),
                actor_type="system",
                actor_id="default",
                created_at=utc_now(),
            )
        )
    await async_session.flush()
    from server.services.workflows import list_node_logs

    logs = await list_node_logs(async_session, run["id"], "script", actor_id="default")

    assert [item["line"] for item in logs["items"]] == ["line-a", "line-b"]

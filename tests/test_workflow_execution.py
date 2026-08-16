"""Execution-engine tests: scheduling, failure propagation, disabled nodes, cancel."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from sqlalchemy import text

from lib.db.models.user import User
from server.services import workflow_execution, workflows

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _seed_user(async_session) -> None:
    if async_session.get_bind().dialect.name == "sqlite":
        await async_session.execute(text("PRAGMA foreign_keys=ON"))
    if await async_session.get(User, "default") is None:
        async_session.add(User(id="default", username="workflow-exec-test"))
        await async_session.flush()


@pytest.fixture(autouse=True)
def _fake_project_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Execution touches the project dir via ProjectManager; tests fake it."""

    class _FakeProjectManager:
        def get_project_path(self, name: str):
            return tmp_path / name

    monkeypatch.setattr(workflow_execution, "get_project_manager", lambda: _FakeProjectManager())


def _chain_nodes() -> list[dict]:
    return [
        {"node_key": "source", "node_type": "source_import", "config": {"source_file": "source/novel.txt"}},
        {"node_key": "build", "node_type": "shot_image_generate", "config": {"episode": 1}},
        {"node_key": "export", "node_type": "export", "config": {}},
    ]


def _chain_edges() -> list[dict]:
    return [
        {"edge_key": "source-build", "source_node_key": "source", "target_node_key": "build"},
        {"edge_key": "build-export", "source_node_key": "build", "target_node_key": "export"},
    ]


async def _published_revision(async_session, nodes: list[dict], edges: list[dict]) -> str:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="demo", name="Demo flow", actor_id="default"
    )
    revision = await workflows.create_revision(
        async_session, definition_id=definition["id"], nodes=nodes, edges=edges, template_lock=None, actor_id="default"
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="default")
    return revision["id"]


async def _running_run(async_session, revision_id: str) -> str:
    planned = await workflows.plan_run(
        async_session,
        revision_id=revision_id,
        workspace_id="default",
        project_id="demo",
        mode="hybrid",
        input_snapshot={"project_id": "demo"},
        script_revision_id=None,
        actor_id="default",
    )
    await workflows.transition_workflow_run(
        async_session, run_id=planned["id"], target="running", expected_version=1, actor_id="default"
    )
    return planned["id"]


def _fake_adapters(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[str],
    handler: Callable[[str, Any], dict],
) -> None:
    async def adapter(ctx: workflow_execution.NodeContext) -> workflow_execution.NodeExecutionResult:
        calls.append(ctx.node_key)
        outputs = handler(ctx.node_key, ctx)
        return workflow_execution.NodeExecutionResult(outputs=outputs, summary=f"{ctx.node_key} done")

    import server.services.workflow_adapters as adapters

    monkeypatch.setattr(adapters, "get_adapter", lambda node_type: adapter)


async def test_executes_chain_in_topological_order(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    revision_id = await _published_revision(async_session, _chain_nodes(), _chain_edges())
    run_id = await _running_run(async_session, revision_id)
    calls: list[str] = []

    def handler(node_key: str, _ctx: Any) -> dict:
        return {"out": [workflow_execution.AssetRef(kind="file", path=f"{node_key}.txt", label=node_key)]}

    _fake_adapters(monkeypatch, calls, handler)

    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "succeeded"
    assert calls == ["source", "build", "export"]
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    assert {node["node_key"]: node["status"] for node in run["nodes"]} == {
        "source": "succeeded",
        "build": "succeeded",
        "export": "succeeded",
    }


async def test_failed_node_fails_run_and_blocks_downstream(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    revision_id = await _published_revision(async_session, _chain_nodes(), _chain_edges())
    run_id = await _running_run(async_session, revision_id)
    calls: list[str] = []

    def handler(node_key: str, _ctx: Any) -> dict:
        if node_key == "build":
            raise RuntimeError("image generation failed")
        return {"out": [workflow_execution.AssetRef(kind="file", path=f"{node_key}.txt", label=node_key)]}

    _fake_adapters(monkeypatch, calls, handler)

    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "failed"
    assert calls == ["source", "build"]
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    statuses = {node["node_key"]: node for node in run["nodes"]}
    assert statuses["build"]["status"] == "failed"
    assert statuses["export"]["status"] == "blocked"
    assert statuses["build"]["error_code"] == "RuntimeError"


async def test_disabled_node_is_skipped_with_pass_through(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    nodes = [
        {"node_key": "source", "node_type": "source_import", "config": {"source_file": "source/novel.txt"}},
        {"node_key": "build", "node_type": "shot_image_generate", "config": {"disabled": True}},
        {"node_key": "export", "node_type": "export", "config": {}},
    ]
    revision_id = await _published_revision(async_session, nodes, _chain_edges())
    run_id = await _running_run(async_session, revision_id)
    calls: list[str] = []

    def handler(node_key: str, _ctx: Any) -> dict:
        return {"out": [workflow_execution.AssetRef(kind="file", path=f"{node_key}.txt", label=node_key)]}

    _fake_adapters(monkeypatch, calls, handler)

    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "succeeded"
    assert calls == ["source", "export"]
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    statuses = {node["node_key"]: node["status"] for node in run["nodes"]}
    assert statuses == {"source": "succeeded", "build": "skipped", "export": "succeeded"}


async def test_cancelled_run_marks_inflight_node_cancelled(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    revision_id = await _published_revision(async_session, _chain_nodes(), _chain_edges())
    run_id = await _running_run(async_session, revision_id)
    calls: list[str] = []

    async def handler(node_key: str, ctx: workflow_execution.NodeContext) -> dict:
        if node_key == "build":
            if await ctx.cancelled():
                raise workflow_execution.NodeCancelledError()
        return {"out": [workflow_execution.AssetRef(kind="file", path=f"{node_key}.txt", label=node_key)]}

    async def adapter(ctx: workflow_execution.NodeContext) -> workflow_execution.NodeExecutionResult:
        calls.append(ctx.node_key)
        outputs = await handler(ctx.node_key, ctx)
        return workflow_execution.NodeExecutionResult(outputs=outputs, summary=f"{ctx.node_key} done")

    import server.services.workflow_adapters as adapters

    monkeypatch.setattr(adapters, "get_adapter", lambda node_type: adapter)

    # Cancel the run right after the first node completes: the engine should
    # stop scheduling and never start the export node.
    original = workflow_execution._execute_node

    async def _execute_with_cancel(*args: Any, **kwargs: Any) -> None:
        await original(*args, **kwargs)
        await workflows.transition_workflow_run(
            async_session, run_id=run_id, target="cancelled", expected_version=2, actor_id="default"
        )

    monkeypatch.setattr(workflow_execution, "_execute_node", _execute_with_cancel)

    await workflow_execution.run_workflow_run(async_session, run_id)

    assert calls == ["source"]
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    assert run["status"] == "cancelled"
    statuses = {node["node_key"]: node["status"] for node in run["nodes"]}
    assert statuses["source"] == "succeeded"
    assert statuses["build"] in {"ready", "blocked"}


async def test_node_logs_are_persisted_as_events(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    revision_id = await _published_revision(async_session, _chain_nodes(), _chain_edges())
    run_id = await _running_run(async_session, revision_id)

    async def adapter(ctx: workflow_execution.NodeContext) -> workflow_execution.NodeExecutionResult:
        ctx.log("info", "line one")
        ctx.log("warn", "line two")
        return workflow_execution.NodeExecutionResult(
            outputs={"out": [workflow_execution.AssetRef(kind="file", path="x.txt", label="x")]},
            summary="done",
        )

    import server.services.workflow_adapters as adapters

    monkeypatch.setattr(adapters, "get_adapter", lambda node_type: adapter)

    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "succeeded"
    events = await workflows.list_events(async_session, "demo", actor_id="default")
    log_events = [event for event in events["items"] if event["event_type"] == "workflow.node_log"]
    assert len(log_events) == 9  # 3 nodes x (2 log lines + 1 summary line)
    lines = [event["payload"]["line"] for event in log_events]
    assert lines.count("line one") == 3
    assert lines.count("line two") == 3

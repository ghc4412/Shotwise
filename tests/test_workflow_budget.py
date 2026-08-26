"""Workflow run budget reservation and terminal cleanup tests."""

from __future__ import annotations

import pytest
from sqlalchemy import text

from lib.db.models.user import User
from lib.workflow import WorkflowValidationError
from server.services import workflow_execution, workflows

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
async def _seed_user(async_session) -> None:
    if async_session.get_bind().dialect.name == "sqlite":
        await async_session.execute(text("PRAGMA foreign_keys=ON"))
    if await async_session.get(User, "default") is None:
        async_session.add(User(id="default", username="workflow-budget-test"))
        await async_session.flush()


@pytest.fixture(autouse=True)
def _fake_project_root(tmp_path, monkeypatch: pytest.MonkeyPatch) -> None:
    class _FakeProjectManager:
        def get_project_path(self, name: str):
            return tmp_path / name

    monkeypatch.setattr(workflow_execution, "get_project_manager", lambda: _FakeProjectManager())


async def _published_revision(async_session) -> str:
    definition = await workflows.create_definition(
        async_session, workspace_id="default", project_id="budget-demo", name="Budget flow", actor_id="default"
    )
    revision = await workflows.create_revision(
        async_session,
        definition_id=definition["id"],
        nodes=[{"node_key": "source", "node_type": "source_import", "config": {}}],
        edges=[],
        template_lock=None,
        actor_id="default",
    )
    await workflows.publish_revision(async_session, revision["id"], actor_id="default")
    return revision["id"]


async def _running_run(async_session, *, budget_limit: float = 10) -> str:
    revision_id = await _published_revision(async_session)
    planned = await workflows.plan_run(
        async_session,
        revision_id=revision_id,
        workspace_id="default",
        project_id="budget-demo",
        mode="hybrid",
        input_snapshot={"project_id": "budget-demo"},
        script_revision_id=None,
        actor_id="default",
        episode_id="episode-1",
        budget_limit=budget_limit,
    )
    await workflows.transition_workflow_run(
        async_session, run_id=planned["id"], target="running", expected_version=1, actor_id="default"
    )
    return planned["id"]


async def test_reservation_settlement_and_release_preserve_episode_budget(async_session) -> None:
    run_id = await _running_run(async_session)
    reservation = await workflows.reserve_run_budget(async_session, run_id, amount=6, actor_id="default")
    assert reservation["reserved_amount"] == 6
    assert reservation["remaining_amount"] == 4

    settled = await workflows.settle_run_budget(
        async_session, reservation["reservation_id"], amount=4, actor_id="default"
    )
    assert settled["spent_amount"] == 4
    assert settled["reserved_amount"] == 2
    assert settled["remaining_amount"] == 4

    released = await workflows.release_run_budget(async_session, reservation["reservation_id"], actor_id="default")
    assert released["spent_amount"] == 4
    assert released["reserved_amount"] == 0
    assert released["remaining_amount"] == 6
    assert (
        await workflows.release_run_budget(async_session, reservation["reservation_id"], actor_id="default") == released
    )

    with pytest.raises(WorkflowValidationError):
        await workflows.settle_run_budget(async_session, reservation["reservation_id"], amount=1, actor_id="default")


async def test_reservation_rejects_budget_overrun(async_session) -> None:
    run_id = await _running_run(async_session, budget_limit=5)
    await workflows.reserve_run_budget(async_session, run_id, amount=4, actor_id="default")
    with pytest.raises(WorkflowValidationError):
        await workflows.reserve_run_budget(async_session, run_id, amount=2, actor_id="default")


async def test_failed_run_releases_unsettled_reservations(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = await _running_run(async_session)
    reservation = await workflows.reserve_run_budget(async_session, run_id, amount=3, actor_id="default")

    async def adapter(_ctx: workflow_execution.NodeContext) -> workflow_execution.NodeExecutionResult:
        raise RuntimeError("generation failed")

    import server.services.workflow_adapters as adapters

    monkeypatch.setattr(adapters, "get_adapter", lambda _node_type: adapter)
    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "failed"
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    assert run["spent_amount"] == 0
    assert run["reserved_amount"] == 0
    assert run["remaining_amount"] == 10
    assert reservation["reservation_id"]


async def test_cancelled_run_releases_unsettled_reservations(async_session, monkeypatch: pytest.MonkeyPatch) -> None:
    run_id = await _running_run(async_session)
    reservation = await workflows.reserve_run_budget(async_session, run_id, amount=3, actor_id="default")

    async def adapter(_ctx: workflow_execution.NodeContext) -> workflow_execution.NodeExecutionResult:
        raise workflow_execution.NodeCancelledError()

    import server.services.workflow_adapters as adapters

    monkeypatch.setattr(adapters, "get_adapter", lambda _node_type: adapter)
    await workflows.transition_workflow_run(
        async_session, run_id=run_id, target="cancelled", expected_version=2, actor_id="default"
    )
    result = await workflow_execution.run_workflow_run(async_session, run_id)

    assert result["status"] == "cancelled"
    run = await workflows.get_run(async_session, run_id, actor_id="default")
    assert run["spent_amount"] == 0
    assert run["reserved_amount"] == 0
    assert run["remaining_amount"] == 10
    assert reservation["reservation_id"]

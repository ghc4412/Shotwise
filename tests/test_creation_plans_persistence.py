from __future__ import annotations

import json
from typing import Any, cast

import pytest
from sqlalchemy import exc as sa_exc
from sqlalchemy import func, select

from lib.db.base import utc_now
from lib.db.models.creation_plan import CreationCompatibilityEvent, CreationPlanRecord
from lib.db.models.creation_skill import CreationSkillDefinitionRecord, CreationSkillVersionRecord
from lib.db.models.workflow import WorkflowDefinition, WorkflowRevision, WorkflowRun
from server.services import creation_plans as service

pytestmark = pytest.mark.unit


def _project(*, generation_mode: str = "storyboard") -> dict[str, object]:
    return {
        "content_mode": "drama",
        "generation_mode": generation_mode,
        "grid_storyboard": False,
        "aspect_ratio": "9:16",
        "style": "cinematic",
        "model_settings": {"image": {"provider": "test", "model": "image-v1"}},
    }


async def _preview(session, *, project, skill="novel-to-drama", key="key-1") -> dict[str, Any]:
    definition = await session.get(WorkflowDefinition, "definition-1")
    if definition is None:
        definition = WorkflowDefinition(
            id="definition-1",
            user_id="user-1",
            workspace_id="workspace-1",
            project_id="project-1",
            name="Test workflow",
            scope="project",
        )
        session.add(definition)
        session.add(
            WorkflowRevision(
                id="revision-1",
                definition_id=definition.id,
                revision_no=1,
                status="published",
                content_mode="drama",
                generation_mode="storyboard",
                input_schema_json="{}",
                graph_hash="graph-hash",
                execution_hash="execution-hash",
                template_lock_json=None,
                created_by="user-1",
                created_at=utc_now(),
            )
        )
        await session.flush()
    return await service.create_creation_plan_preview(
        session,
        user_id="user-1",
        workspace_id="workspace-1",
        project_id="project-1",
        creation_skill_version_id=f"{skill}:v1",
        project=project,
        resource_ids=["doc-1"],
        resource_types=["document"],
        parameters={"duration": 8},
        workflow_revision=None,
        estimated_cost=1.25,
        steps=["script", "video"],
        review_points=["quality"],
        idempotency_key=key,
    )


@pytest.mark.asyncio
async def test_preview_is_immutable_and_idempotent(async_session):
    first = await _preview(async_session, project=_project())
    second = await _preview(async_session, project=_project())

    assert first["plan_id"] == second["plan_id"]
    assert second["deduped"] is True
    record = await async_session.get(CreationPlanRecord, first["plan_id"])
    assert record is not None
    assert json.loads(record.project_snapshot_json)["generation_mode"] == "storyboard"


@pytest.mark.asyncio
async def test_preview_uses_published_revision_cost_and_capabilities(async_session):
    result = await _preview(async_session, project=_project(), key="revision-source")

    assert result["workflow_revision"]
    assert result["required_capabilities"] == []
    assert result["estimated_cost"] == 0.0
    assert result["capability_report"]["compatible"] is True


@pytest.mark.asyncio
async def test_preview_persists_source_aware_resource_mapping(async_session):
    result = cast(
        dict[str, Any],
        await service.create_creation_plan_preview(
            async_session,
            user_id="user-1",
            workspace_id="workspace-1",
            project_id="project-1",
            creation_skill_version_id="novel-to-drama:v1",
            project=_project(),
            resource_ids=["doc-1", "asset-1"],
            resource_types=["document", "image"],
            resource_mapping=[
                {"id": "doc-1", "type": "document", "source": "project_entity"},
                {"id": "asset-1", "type": "image", "source": "media_asset"},
            ],
            parameters={"duration": 12},
            workflow_revision=None,
            estimated_cost=None,
            steps=None,
            review_points=None,
            idempotency_key="source-aware-resources",
        ),
    )

    assert result["resource_mapping"] == [
        {"id": "doc-1", "type": "document", "source": "project_entity"},
        {"id": "asset-1", "type": "image", "source": "media_asset"},
    ]
    assert result["parameters"] == {"duration": 12}


@pytest.mark.asyncio
async def test_incompatible_preview_is_structured_and_never_starts_a_run(async_session, monkeypatch):
    result = await _preview(
        async_session,
        project=_project(),
        skill="reference-image-video",
        key="incompatible",
    )

    assert result["compatibility_report"]["compatible"] is False
    assert result["compatibility_report"]["project_generation_mode"] == "storyboard"
    assert result["compatibility_report"]["requires_new_project"] is True
    event_count = await async_session.scalar(select(func.count()).select_from(CreationCompatibilityEvent))
    assert event_count == 1

    async def fail_if_called(*args, **kwargs):
        raise AssertionError("incompatible plans must not create WorkflowRuns")

    monkeypatch.setattr(service.workflow_service, "plan_run", fail_if_called)
    with pytest.raises(service.CreationPlanStartError, match="creation_skill_incompatible"):
        await service.start_creation_plan(
            async_session,
            str(result["plan_id"]),
            user_id="user-1",
            project=_project(),
            cost_confirmed=True,
            review_confirmed=True,
        )
    assert await async_session.scalar(select(func.count()).select_from(CreationPlanRecord)) == 1


@pytest.mark.asyncio
async def test_incompatibility_outcome_records_only_coarse_choice(async_session):
    result = await _preview(
        async_session,
        project=_project(),
        skill="reference-image-video",
        key="outcome",
    )
    event_id = str(result["compatibility_report"]["event_id"])

    recorded = await service.record_compatibility_outcome(
        async_session,
        event_id,
        outcome="alternative_skill",
    )

    assert recorded == {
        "event_id": event_id,
        "creation_skill_version_id": "reference-image-video:v1",
        "project_generation_mode": "storyboard",
        "outcome": "alternative_skill",
    }
    event = await async_session.get(CreationCompatibilityEvent, event_id)
    assert event is not None
    assert event.outcome == "alternative_skill"


@pytest.mark.asyncio
async def test_start_rechecks_project_snapshot_and_dedupes(async_session, monkeypatch):
    result = await _preview(async_session, project=_project(), key="start")
    calls = 0

    async def fake_plan_run(*args, **kwargs):
        nonlocal calls
        calls += 1
        record = await async_session.get(CreationPlanRecord, str(result["plan_id"]))
        assert record is not None
        async_session.add(
            WorkflowRun(
                id="run-1",
                user_id="user-1",
                workflow_revision_id=record.workflow_revision,
                workspace_id=record.workspace_id,
                project_id=record.project_id,
                status="running",
                mode="hybrid",
                execution_hash="test-execution-hash",
                input_fingerprint="test-input-fingerprint",
                graph_snapshot_ref=record.workflow_revision,
                input_snapshot_json=json.dumps({"creation_plan_id": record.id}),
                progress=0,
                version=2,
                control_generation=0,
                trace_id="trace-run-1",
                created_by="user-1",
                created_at=utc_now(),
            )
        )
        await async_session.flush()
        return {"id": "run-1", "status": "running", "version": 2, "deduped": False}

    monkeypatch.setattr(service.workflow_service, "plan_run", fake_plan_run)
    dispatches: list[str] = []

    async def fake_dispatch(*args, **kwargs):
        dispatches.append(str(kwargs["run_id"]))
        return {"dispatch_status": "queued"}

    monkeypatch.setattr(service.workflow_service, "request_workflow_run_execution", fake_dispatch)
    changed = _project()
    changed["style"] = "different"
    with pytest.raises(service.CreationPlanStartError, match="project_snapshot_changed"):
        await service.start_creation_plan(
            async_session,
            str(result["plan_id"]),
            user_id="user-1",
            project=changed,
        )
    assert calls == 0

    first = await service.start_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=_project(),
        cost_confirmed=True,
        review_confirmed=True,
    )
    second = await service.start_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=_project(),
        cost_confirmed=True,
        review_confirmed=True,
    )
    assert first["workflow_run_id"] == second["workflow_run_id"] == "run-1"
    assert second["deduped"] is True
    assert calls == 1
    assert dispatches == ["run-1", "run-1"]


@pytest.mark.asyncio
async def test_start_transitions_a_real_planned_workflow_run_to_running(async_session, monkeypatch):
    result = await _preview(async_session, project=_project(), key="real-start")
    calls: list[str] = []

    async def fake_plan_run(*args, **kwargs):
        return {"id": "run-1", "status": "planned", "version": 1, "deduped": False}

    async def fake_transition(*args, **kwargs):
        calls.append(kwargs["target"])
        return {"id": "run-1", "status": "running", "version": 2}

    monkeypatch.setattr(service.workflow_service, "plan_run", fake_plan_run)
    monkeypatch.setattr(service.workflow_service, "transition_workflow_run", fake_transition)
    dispatches: list[str] = []

    async def fake_dispatch(*args, **kwargs):
        dispatches.append(str(kwargs["run_id"]))
        return {"dispatch_status": "queued"}

    monkeypatch.setattr(service.workflow_service, "request_workflow_run_execution", fake_dispatch)

    started = await service.start_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=_project(),
        cost_confirmed=True,
        review_confirmed=True,
    )

    assert started["status"] == "running"
    assert calls == ["running"]
    assert dispatches == ["run-1"]


@pytest.mark.asyncio
async def test_restart_creates_a_new_run_only_after_terminal_run(async_session, monkeypatch):
    result = await _preview(async_session, project=_project(), key="restart")
    calls: list[dict[str, Any]] = []
    run_ids = iter(("run-1", "run-2"))

    async def fake_plan_run(*args, **kwargs):
        calls.append(kwargs)
        return {"id": next(run_ids), "status": "planned", "version": 1, "deduped": False}

    async def fake_transition(*args, **kwargs):
        return {"id": "run-2", "status": "running", "version": 2}

    monkeypatch.setattr(service.workflow_service, "plan_run", fake_plan_run)
    monkeypatch.setattr(service.workflow_service, "transition_workflow_run", fake_transition)

    async def fake_dispatch(*args, **kwargs):
        return {"dispatch_status": "queued"}

    monkeypatch.setattr(service.workflow_service, "request_workflow_run_execution", fake_dispatch)
    first_run = await service.start_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=_project(),
        cost_confirmed=True,
        review_confirmed=True,
    )
    record = await async_session.get(service.CreationPlanRecord, str(result["plan_id"]))
    assert record is not None
    async_session.add(
        WorkflowRun(
            id="run-1",
            workflow_revision_id=record.workflow_revision,
            workspace_id=record.workspace_id,
            project_id=record.project_id,
            status="failed",
            mode="hybrid",
            execution_hash="test-execution-hash",
            input_fingerprint="test-input-fingerprint",
            input_snapshot_json="{}",
            trace_id="trace-run-1",
            created_by="user-1",
            created_at=utc_now(),
        )
    )
    await async_session.flush()
    record.status = "failed"
    record.workflow_run_id = "run-1"
    await async_session.commit()
    restarted = await service.restart_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=_project(),
    )

    assert first_run["workflow_run_id"] == "run-1"
    assert restarted["workflow_run_id"] == "run-2"
    assert restarted["status"] == "running"
    input_snapshot = cast(dict[str, Any], calls[-1]["input_snapshot"])
    assert input_snapshot["restart_of_workflow_run_id"] == "run-1"


@pytest.mark.asyncio
async def test_recompile_creates_a_new_snapshot_and_invalidates_old_plan(async_session):
    result = await _preview(async_session, project=_project(), key="recompile")
    changed = _project()
    changed["style"] = "updated"

    recompiled = await service.recompile_creation_plan(
        async_session,
        str(result["plan_id"]),
        user_id="user-1",
        project=changed,
    )

    assert recompiled["plan_id"] != result["plan_id"]
    assert recompiled["recompiled_from"] == result["plan_id"]
    old = await async_session.get(CreationPlanRecord, str(result["plan_id"]))
    assert old is not None
    assert old.status == "invalidated"
    new = await async_session.get(CreationPlanRecord, str(recompiled["plan_id"]))
    assert new is not None
    assert json.loads(new.project_snapshot_json)["style"] == "updated"


@pytest.mark.asyncio
async def test_preview_rejects_empty_resources(async_session):
    with pytest.raises(Exception, match="real resource"):
        await service.create_creation_plan_preview(
            async_session,
            user_id="user-1",
            workspace_id="workspace-1",
            project_id="project-1",
            creation_skill_version_id="novel-to-drama:v1",
            project=_project(),
            resource_ids=[],
            resource_types=["document"],
            parameters={},
            workflow_revision="revision-1",
            estimated_cost=0,
            steps=[],
            review_points=[],
            idempotency_key="empty-resources",
        )


@pytest.mark.asyncio
async def test_published_skill_version_requires_a_workflow_revision(async_session):
    async_session.add(CreationSkillDefinitionRecord(id="skill-1", slug="skill-1"))
    async_session.add(
        CreationSkillVersionRecord(
            id="skill-1:v1",
            skill_id="skill-1",
            version=1,
            title="Skill",
            summary="Summary",
            category="test",
            workflow_template_revision_alias="legacy",
            workflow_revision_id=None,
            status="published",
            frozen_at=utc_now(),
        )
    )

    with pytest.raises(sa_exc.IntegrityError):
        await async_session.flush()

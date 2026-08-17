"""Shotwise Flow API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import BadRequestError
from lib.db import get_async_session
from lib.workflow import WorkflowValidationError
from server.auth import CurrentUser
from server.services import workflows as service

router = APIRouter()


class DefinitionCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


class WorkflowNodeInput(BaseModel):
    node_key: str = Field(min_length=1, max_length=128)
    node_type: str = Field(min_length=1, max_length=128)
    node_type_version: str = "1"
    config_schema_version: str = "1"
    config: dict[str, Any] = Field(default_factory=dict)
    ui_position: dict[str, Any] | None = None
    weight: float = Field(default=1, gt=0)
    retry_policy: dict[str, Any] | None = None
    approval_policy: dict[str, Any] | None = None


class WorkflowEdgeInput(BaseModel):
    edge_key: str = Field(min_length=1, max_length=128)
    source_node_key: str = Field(min_length=1, max_length=128)
    target_node_key: str = Field(min_length=1, max_length=128)
    condition: dict[str, Any] | None = None
    on_failure: Literal["stop", "skip", "fallback"] = "stop"
    priority: int = 0


class RevisionCreate(BaseModel):
    nodes: list[WorkflowNodeInput] = Field(min_length=1, max_length=1000)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list, max_length=5000)
    template_lock: dict[str, Any] | None = None


class RunCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    script_revision_id: str | None = None
    mode: Literal["auto", "manual", "hybrid"] = "hybrid"
    input_snapshot: dict[str, Any] = Field(default_factory=dict)


class RunTransition(BaseModel):
    expected_version: int = Field(ge=1)


class RetryNodeRequest(BaseModel):
    node_key: str = Field(min_length=1, max_length=128)
    start: bool = True


def _translate_validation(exc: WorkflowValidationError) -> None:
    raise BadRequestError(exc.code, **exc.params) from exc


@router.post("/workflows")
async def create_workflow(
    body: DefinitionCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.create_definition(
        session,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        name=body.name,
        actor_id=user.id,
    )


@router.get("/workflows/{definition_id}")
async def get_workflow(
    definition_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.get_workflow(session, definition_id, actor_id=user.id)


@router.post("/workflows/{definition_id}/revisions")
async def create_revision(
    definition_id: str,
    body: RevisionCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.create_revision(
            session,
            definition_id=definition_id,
            nodes=[node.model_dump() for node in body.nodes],
            edges=[edge.model_dump() for edge in body.edges],
            template_lock=body.template_lock,
            actor_id=user.id,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-revisions/{revision_id}/validate")
async def validate_revision(
    revision_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.validate_revision(session, revision_id, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-revisions/{revision_id}/publish")
async def publish_revision(
    revision_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.publish_revision(session, revision_id, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/workflows/{definition_id}/revisions")
async def list_workflow_revisions(
    definition_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_revisions(session, definition_id, actor_id=user.id)


@router.post("/workflows/{definition_id}/revisions/{revision_id}/revert")
async def revert_workflow_revision(
    definition_id: str,
    revision_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.revert_revision(
            session,
            definition_id=definition_id,
            revision_id=revision_id,
            actor_id=user.id,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-revisions/{revision_id}/runs")
async def plan_run(
    revision_id: str,
    body: RunCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.plan_run(
            session,
            revision_id=revision_id,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            script_revision_id=body.script_revision_id,
            mode=body.mode,
            input_snapshot=body.input_snapshot,
            actor_id=user.id,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/workflow-runs/{run_id}")
async def get_run(run_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)):
    return await service.get_run(session, run_id, actor_id=user.id)


@router.post("/workflow-runs/{run_id}/retry")
async def retry_workflow_run(
    run_id: str,
    body: RetryNodeRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.retry_run_from_node(
            session,
            run_id=run_id,
            node_key=body.node_key,
            actor_id=user.id,
            start=body.start,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/workflow-templates")
async def list_workflow_templates(user: CurrentUser):
    del user
    return service.list_templates()


@router.get("/projects/{project_id}/workflow-runs")
async def list_runs(
    project_id: str,
    user: CurrentUser,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_runs(session, project_id, actor_id=user.id, limit=limit)


async def _transition(
    run_id: str,
    target: str,
    body: RunTransition,
    user: CurrentUser,
    session: AsyncSession,
):
    try:
        return await service.transition_workflow_run(
            session,
            run_id=run_id,
            target=target,
            expected_version=body.expected_version,
            actor_id=user.id,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/projects/{project_id}/workflows")
async def list_workflows(
    project_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_definitions(session, project_id, actor_id=user.id)


@router.get("/workflows/{definition_id}/export")
async def export_workflow(
    definition_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.export_definition(session, definition_id, actor_id=user.id)


class WorkflowImport(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=200)
    nodes: list[WorkflowNodeInput] = Field(min_length=1, max_length=1000)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list, max_length=5000)
    template_lock: dict[str, Any] | None = None


@router.post("/projects/{project_id}/workflows/import")
async def import_workflow(
    project_id: str,
    body: WorkflowImport,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.import_definition(
            session,
            workspace_id=body.workspace_id,
            project_id=project_id,
            name=body.name,
            nodes=[node.model_dump() for node in body.nodes],
            edges=[edge.model_dump() for edge in body.edges],
            template_lock=body.template_lock,
            actor_id=user.id,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


class WorkspaceScope(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)


@router.post("/projects/{project_id}/workflows/migrate")
async def migrate_project(
    project_id: str,
    body: WorkspaceScope,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.migrate_project(
        session,
        workspace_id=body.workspace_id,
        project_id=project_id,
        actor_id=user.id,
    )


@router.get("/workflow-runs/{run_id}/nodes/{node_key}/log")
async def get_node_logs(
    run_id: str,
    node_key: str,
    user: CurrentUser,
    limit: int = Query(default=500, ge=1, le=2000),
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_node_logs(session, run_id, node_key, actor_id=user.id, limit=limit)


@router.post("/workflow-runs/{run_id}/start")
async def start_run(
    run_id: str, body: RunTransition, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await _transition(run_id, "running", body, user, session)


@router.post("/workflow-runs/{run_id}/pause")
async def pause_run(
    run_id: str, body: RunTransition, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await _transition(run_id, "paused", body, user, session)


@router.post("/workflow-runs/{run_id}/resume")
async def resume_run(
    run_id: str, body: RunTransition, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await _transition(run_id, "running", body, user, session)


@router.post("/workflow-runs/{run_id}/cancel")
async def cancel_run(
    run_id: str, body: RunTransition, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await _transition(run_id, "cancelled", body, user, session)


@router.get("/projects/{project_id}/event-log")
async def replay_project_events(
    project_id: str,
    user: CurrentUser,
    after: int = Query(default=0, ge=0),
    limit: int = Query(default=500, ge=1, le=1000),
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_events(session, project_id, actor_id=user.id, after=after, limit=limit)

"""Shotwise Flow API."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import BadRequestError
from lib.db import get_async_session
from lib.db.models.workflow import BudgetReservation
from lib.workflow import WorkflowPatch, WorkflowValidationError
from server.auth import AdminUser, CurrentUser
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
    content_mode: Literal["manga", "drama", "narration", "ad"] = "drama"
    generation_mode: Literal["storyboard", "reference_video"] = "storyboard"
    input_schema: dict[str, Any] = Field(default_factory=dict)


class RunCreate(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    script_revision_id: str | None = None
    mode: Literal["auto", "manual", "hybrid"] = "hybrid"
    input_snapshot: dict[str, Any] = Field(default_factory=dict)
    episode_id: str | None = Field(default=None, max_length=128)
    budget_limit: float | None = Field(default=None, ge=0)


class RunTransition(BaseModel):
    expected_version: int = Field(ge=1)


class RetryNodeRequest(BaseModel):
    node_key: str = Field(min_length=1, max_length=128)
    start: bool = True


class TemplateUpgradeApplyRequest(BaseModel):
    confirmed: bool = False


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


@router.get("/workflows/{definition_id}/template-upgrade")
async def get_template_upgrade(
    definition_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.get_template_upgrade(session, definition_id, actor_id=user.id)


@router.post("/workflows/{definition_id}/template-upgrade")
async def apply_template_upgrade(
    definition_id: str,
    body: TemplateUpgradeApplyRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.upgrade_workflow_template(
            session,
            definition_id,
            actor_id=user.id,
            confirmed=body.confirmed,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


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
            content_mode=body.content_mode,
            generation_mode=body.generation_mode,
            input_schema=body.input_schema,
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
            episode_id=body.episode_id,
            budget_limit=body.budget_limit,
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
async def list_workflow_templates(
    user: CurrentUser,
    template_type: Literal["manga", "short_drama"] | None = Query(default=None),
    session: AsyncSession = Depends(get_async_session),
):
    marketplace = (
        await service.list_marketplace(session, template_type=template_type)
        if service.marketplace_public_enabled() or user.role == "admin"
        else {"items": []}
    )
    builtin = service.list_templates()
    return {"items": [*builtin["items"], *marketplace["items"]]}


class TemplateDraftCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=5000)
    template_type: Literal["manga", "short_drama"]
    contract: dict[str, Any] = Field(default_factory=dict)
    nodes: list[WorkflowNodeInput] = Field(min_length=1, max_length=1000)
    edges: list[WorkflowEdgeInput] = Field(default_factory=list, max_length=5000)
    content_mode: Literal["manga", "drama", "narration", "ad"] = "drama"
    generation_mode: Literal["storyboard", "reference_video"] = "storyboard"
    cover_ref: str | None = Field(default=None, max_length=500)


@router.post("/workflow-templates")
async def create_workflow_template(
    body: TemplateDraftCreate, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    if user.role != "admin" and not service.template_upload_enabled():
        raise HTTPException(status_code=403, detail="workflow_template_upload_disabled")
    try:
        return await service.create_template_draft(
            session,
            name=body.name,
            description=body.description,
            template_type=body.template_type,
            contract=body.contract,
            nodes=[node.model_dump() for node in body.nodes],
            edges=[edge.model_dump() for edge in body.edges],
            actor_id=user.id,
            content_mode=body.content_mode,
            generation_mode=body.generation_mode,
            cover_ref=body.cover_ref,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


class TemplateDraftUpdate(TemplateDraftCreate):
    pass


@router.get("/workflow-templates/mine")
async def list_creator_workflow_templates(user: CurrentUser, session: AsyncSession = Depends(get_async_session)):
    return await service.list_creator_templates(session, actor_id=user.id)


@router.put("/workflow-templates/{template_id}")
async def update_workflow_template(
    template_id: str,
    body: TemplateDraftUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.update_template_draft(
            session,
            template_id,
            name=body.name,
            description=body.description,
            template_type=body.template_type,
            contract=body.contract,
            nodes=[node.model_dump() for node in body.nodes],
            edges=[edge.model_dump() for edge in body.edges],
            actor_id=user.id,
            content_mode=body.content_mode,
            generation_mode=body.generation_mode,
            cover_ref=body.cover_ref,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/workflow-templates/{template_id}")
async def get_workflow_template(
    template_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await service.get_template(
        session,
        template_id,
        actor_id=user.id,
        public=service.marketplace_public_enabled() or user.role == "admin",
    )


@router.post("/workflow-templates/{template_id}/view")
async def record_workflow_template_view(
    template_id: str, _user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    return await service.record_template_view(session, template_id)


class TemplateRatingRequest(BaseModel):
    rating: float = Field(ge=1, le=5)


@router.post("/workflow-templates/{template_id}/rating")
async def rate_workflow_template(
    template_id: str,
    body: TemplateRatingRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.rate_template(session, template_id, rating=body.rating, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-templates/{template_id}/submit")
async def submit_workflow_template(
    template_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    try:
        return await service.submit_template(session, template_id, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-templates/{template_id}/withdraw")
async def withdraw_workflow_template(
    template_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    try:
        return await service.withdraw_template(session, template_id, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


class TemplateReviewRequest(BaseModel):
    decision: Literal["start", "approve", "reject", "changes_requested"]
    comment: str = Field(min_length=1, max_length=5000)


@router.post("/admin/workflow-templates/{template_id}/review")
async def review_workflow_template(
    template_id: str,
    body: TemplateReviewRequest,
    admin: AdminUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.review_template(
            session, template_id, reviewer_id=admin.id, decision=body.decision, comment=body.comment
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/admin/workflow-templates/{template_id}/suspend")
async def suspend_workflow_template(
    template_id: str, admin: AdminUser, session: AsyncSession = Depends(get_async_session)
):
    return await service.set_template_suspended(session, template_id, reviewer_id=admin.id, suspended=True)


@router.post("/admin/workflow-templates/{template_id}/restore")
async def restore_workflow_template(
    template_id: str, admin: AdminUser, session: AsyncSession = Depends(get_async_session)
):
    return await service.set_template_suspended(session, template_id, reviewer_id=admin.id, suspended=False)


class TemplateDeriveRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    name: str = Field(min_length=1, max_length=200)


@router.post("/workflow-templates/{template_id}/derive")
async def derive_workflow_template(
    template_id: str,
    body: TemplateDeriveRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    return await service.derive_template(
        session,
        template_id,
        workspace_id=body.workspace_id,
        project_id=body.project_id,
        name=body.name,
        actor_id=user.id,
    )


class WorkflowPatchRequest(BaseModel):
    patch: dict[str, Any]
    confirmed: bool = False
    start: bool = False


class BudgetReservationRequest(BaseModel):
    amount: float = Field(gt=0)


@router.post("/workflow-runs/{run_id}/budget/reserve")
async def reserve_workflow_budget(
    run_id: str,
    body: BudgetReservationRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.reserve_run_budget(session, run_id, amount=body.amount, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


class BudgetSettlementRequest(BaseModel):
    reservation_id: str = Field(min_length=1, max_length=36)
    amount: float = Field(ge=0)


@router.post("/workflow-runs/{run_id}/budget/settle")
async def settle_workflow_budget(
    run_id: str,
    body: BudgetSettlementRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    reservation = await session.get(BudgetReservation, body.reservation_id)
    if reservation is None or reservation.workflow_run_id != run_id:
        raise HTTPException(status_code=404, detail="workflow_budget_reservation_not_found")
    try:
        return await service.settle_run_budget(session, body.reservation_id, amount=body.amount, actor_id=user.id)
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-runs/{run_id}/patch/validate")
async def validate_workflow_patch(
    run_id: str, body: WorkflowPatchRequest, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    if not service.auto_optimization_enabled():
        operations = body.patch.get("operations")
        if isinstance(operations, list):
            for operation in operations:
                if isinstance(operation, dict):
                    operation["requires_confirmation"] = True
    try:
        return await service.validate_patch_for_run(
            session, run_id, WorkflowPatch.model_validate(body.patch), actor_id=user.id
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.post("/workflow-runs/{run_id}/patch/apply")
async def apply_workflow_patch(
    run_id: str, body: WorkflowPatchRequest, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    if not service.auto_optimization_enabled() and not body.confirmed:
        raise HTTPException(status_code=409, detail="workflow_patch_confirmation_required")
    try:
        return await service.apply_patch_for_run(
            session,
            run_id,
            WorkflowPatch.model_validate(body.patch),
            actor_id=user.id,
            confirmed=body.confirmed,
            start=body.start,
        )
    except WorkflowValidationError as exc:
        _translate_validation(exc)


@router.get("/admin/workflow-templates/reviews")
async def list_workflow_template_reviews(
    _admin: AdminUser,
    template_type: Literal["manga", "short_drama"] | None = Query(default=None),
    risk_tag: str | None = Query(default=None, max_length=64),
    limit: int = Query(default=100, ge=1, le=200),
    session: AsyncSession = Depends(get_async_session),
):
    return await service.list_pending_template_reviews(
        session, template_type=template_type, risk_tag=risk_tag, limit=limit
    )


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
    content_mode: Literal["manga", "drama", "narration", "ad"] = "drama"
    generation_mode: Literal["storyboard", "reference_video"] = "storyboard"
    input_schema: dict[str, Any] = Field(default_factory=dict)


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
            content_mode=body.content_mode,
            generation_mode=body.generation_mode,
            input_schema=body.input_schema,
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

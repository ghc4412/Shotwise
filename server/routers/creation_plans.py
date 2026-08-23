"""Creation Plan preview and lifecycle API."""

from __future__ import annotations

import asyncio
from collections.abc import Mapping
from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.creation_plan import CreationPlanError
from lib.db import get_async_session
from lib.feature_flags import feature_enabled
from server.auth import AdminUser, CurrentUser
from server.routers.projects import get_project_manager
from server.services import creation_plans as service
from server.services import creation_skill_catalog


def _require_feature() -> None:
    if not feature_enabled("creation_plan") or not feature_enabled("official_creation_skills"):
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "feature": "creation_plan"})


router = APIRouter(dependencies=[Depends(_require_feature)])


class CreationPlanPreviewRequest(BaseModel):
    workspace_id: str = Field(min_length=1, max_length=128)
    project_id: str = Field(min_length=1, max_length=200)
    creation_skill_version_id: str = Field(min_length=1, max_length=128)
    resource_ids: list[str] = Field(default_factory=list, max_length=1000)
    resource_types: list[str] = Field(default_factory=list, max_length=32)
    resource_mapping: list[dict[str, str]] = Field(default_factory=list, max_length=1000)
    parameters: dict[str, Any] = Field(default_factory=dict)
    workflow_revision: str | None = Field(default=None, min_length=1, max_length=128)
    estimated_cost: float | None = Field(default=None, ge=0)
    steps: list[str] | None = Field(default=None, max_length=256)
    review_points: list[str] | None = Field(default=None, max_length=256)
    idempotency_key: str = Field(min_length=1, max_length=256)


class CreationPlanStartRequest(BaseModel):
    mode: Literal["auto", "manual", "hybrid"] = "hybrid"
    script_revision_id: str | None = None
    episode_id: str | None = None
    budget_limit: float | None = Field(default=None, ge=0)
    cost_confirmed: bool = False
    review_confirmed: bool = False


class CompatibilityOutcomeRequest(BaseModel):
    outcome: Literal["cancelled", "alternative_skill", "new_project"]


def _load_project(project_id: str) -> dict[str, object]:
    manager = get_project_manager()
    if not manager.project_exists(project_id):
        raise HTTPException(status_code=404, detail="project_not_found")
    return manager.load_project(project_id)


@router.get("/creation-skills")
async def list_creation_skills(
    project_id: str,
    resource_types: list[str] = [],
    session: AsyncSession = Depends(get_async_session),
):
    project = await asyncio.to_thread(_load_project, project_id)
    return {"items": await creation_skill_catalog.list_creation_skills(session, project, set(resource_types))}


@router.get("/creation-skills/{skill_id}/versions")
async def list_creation_skill_versions(skill_id: str, session: AsyncSession = Depends(get_async_session)):
    return {"items": await creation_skill_catalog.list_creation_skill_versions(session, skill_id)}


@router.get("/creation-resources")
async def list_creation_resources(project_id: str):
    project = await asyncio.to_thread(_load_project, project_id)
    return {"items": service.list_creation_resources(project)}


@router.post("/creation-skills/{skill_id}/deactivate")
async def deactivate_creation_skill(
    skill_id: str, _user: AdminUser, session: AsyncSession = Depends(get_async_session)
):
    if not await creation_skill_catalog.deactivate_creation_skill(session, skill_id, actor_role=_user.role):
        raise HTTPException(status_code=404, detail="creation_skill_not_found")
    return {"id": skill_id, "active": False}


@router.post("/creation-plans/preview")
async def preview_creation_plan(
    body: CreationPlanPreviewRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    project = await asyncio.to_thread(_load_project, body.project_id)
    try:
        return await service.create_creation_plan_preview(
            session,
            user_id=user.id,
            workspace_id=body.workspace_id,
            project_id=body.project_id,
            creation_skill_version_id=body.creation_skill_version_id,
            project=project,
            resource_ids=body.resource_ids,
            resource_types=body.resource_types,
            resource_mapping=body.resource_mapping,
            parameters=body.parameters,
            workflow_revision=body.workflow_revision,
            estimated_cost=body.estimated_cost,
            steps=body.steps,
            review_points=body.review_points,
            idempotency_key=body.idempotency_key,
        )
    except CreationPlanError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/creation-plans/{plan_id}")
async def get_creation_plan(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.get_creation_plan(session, plan_id, user_id=user.id)
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc


@router.post("/creation-plans/{plan_id}/start")
async def start_creation_plan(
    plan_id: str,
    body: CreationPlanStartRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    plan = await service.get_creation_plan(session, plan_id, user_id=user.id)
    project_context = plan.get("project_context")
    if not isinstance(project_context, Mapping):
        raise HTTPException(status_code=500, detail="creation_plan_snapshot_invalid")
    project_id = str(project_context.get("project_id", ""))
    project = await asyncio.to_thread(_load_project, project_id)
    try:
        return await service.start_creation_plan(
            session,
            plan_id,
            user_id=user.id,
            project=project,
            mode=body.mode,
            script_revision_id=body.script_revision_id,
            episode_id=body.episode_id,
            budget_limit=body.budget_limit,
            cost_confirmed=body.cost_confirmed,
            review_confirmed=body.review_confirmed,
        )
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc
    except service.CreationPlanStartError as exc:
        status = 409
        detail: object = {"code": exc.code, **exc.report}
        raise HTTPException(status_code=status, detail=detail) from exc


@router.post("/creation-plans/{plan_id}/cancel")
async def cancel_creation_plan(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.cancel_creation_plan(session, plan_id, user_id=user.id)
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc


@router.post("/creation-plans/{plan_id}/invalidate")
async def invalidate_creation_plan(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.invalidate_creation_plan(session, plan_id, user_id=user.id)
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc
    except service.CreationPlanStartError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code}) from exc


@router.post("/creation-plans/{plan_id}/restart")
async def restart_creation_plan(
    plan_id: str,
    body: CreationPlanStartRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    plan = await service.get_creation_plan(session, plan_id, user_id=user.id)
    project_context = plan.get("project_context")
    if not isinstance(project_context, Mapping):
        raise HTTPException(status_code=500, detail="creation_plan_snapshot_invalid")
    project_id = str(project_context.get("project_id", ""))
    project = await asyncio.to_thread(_load_project, project_id)
    try:
        return await service.restart_creation_plan(
            session,
            plan_id,
            user_id=user.id,
            project=project,
            mode=body.mode,
            script_revision_id=body.script_revision_id,
            episode_id=body.episode_id,
            budget_limit=body.budget_limit,
        )
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc
    except service.CreationPlanStartError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, **exc.report}) from exc


@router.post("/creation-plans/{plan_id}/recompile")
async def recompile_creation_plan(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    plan = await service.get_creation_plan(session, plan_id, user_id=user.id)
    project_context = plan.get("project_context")
    if not isinstance(project_context, Mapping):
        raise HTTPException(status_code=500, detail="creation_plan_snapshot_invalid")
    project_id = str(project_context.get("project_id", ""))
    project = await asyncio.to_thread(_load_project, project_id)
    try:
        return await service.recompile_creation_plan(
            session,
            plan_id,
            user_id=user.id,
            project=project,
        )
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="creation_plan_not_found") from exc
    except service.CreationPlanStartError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, **exc.report}) from exc


@router.post("/creation-compatibility-events/{event_id}/outcome")
async def record_compatibility_outcome(
    event_id: str,
    body: CompatibilityOutcomeRequest,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.record_compatibility_outcome(session, event_id, outcome=body.outcome)
    except service.CreationPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="compatibility_event_not_found") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="invalid_compatibility_outcome") from exc


@router.get("/creation-compatibility-events/metrics")
async def get_compatibility_metrics(session: AsyncSession = Depends(get_async_session)):
    return await service.compatibility_metrics(session)

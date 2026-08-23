"""Structured context resolution for context-aware creation Skills and Agents."""

from __future__ import annotations

import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.creative_context import (
    ContextReference,
    CreativeContextResolutionError,
    SelectedResource,
    resolve_context_references,
    resolve_creation_context,
)
from lib.db import get_async_session
from lib.db.models.creation_plan import CreationPlanRecord
from lib.db.models.creative_board import CreativeBoard, CreativeBoardItem
from lib.db.models.workflow import WorkflowRevision, WorkflowRun
from lib.feature_flags import feature_enabled
from server.auth import CurrentUser
from server.routers.projects import get_project_manager


def _require_feature() -> None:
    if not feature_enabled("context_agent"):
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "feature": "context_agent"})


router = APIRouter(dependencies=[Depends(_require_feature)])


class SelectedResourceRequest(BaseModel):
    id: str = Field(min_length=1, max_length=256)
    resource_type: str = Field(min_length=1, max_length=32)


class ContextReferenceRequest(BaseModel):
    text: str = Field(min_length=1, max_length=128)
    expected_type: str | None = Field(default=None, max_length=32)


class CreativeContextRequest(BaseModel):
    creative_board_id: str = Field(min_length=1, max_length=36)
    episode_id: str | None = Field(default=None, max_length=128)
    shot_id: str | None = Field(default=None, max_length=128)
    selected_resources: list[SelectedResourceRequest] = Field(default_factory=list, max_length=1000)
    context_references: list[ContextReferenceRequest] = Field(default_factory=list, max_length=32)
    current_skill_id: str | None = Field(default=None, max_length=128)
    creation_plan_id: str = Field(min_length=1, max_length=80)
    workflow_run_id: str | None = Field(default=None, max_length=36)
    previewed: bool | None = None
    confirmed: bool = False
    quality_gate_passed: bool | None = None
    approval_status: str | None = Field(default=None, max_length=24)
    allow_gate_bypass: bool = False
    generation_mode: str | None = Field(default=None, max_length=32)
    generation_mode_override: str | None = Field(default=None, max_length=32)


class ContextReferenceResolutionRequest(BaseModel):
    creative_board_id: str = Field(min_length=1, max_length=36)
    episode_id: str | None = Field(default=None, max_length=128)
    shot_id: str | None = Field(default=None, max_length=128)
    selected_resources: list[SelectedResourceRequest] = Field(default_factory=list, max_length=1000)
    context_references: list[ContextReferenceRequest] = Field(min_length=1, max_length=32)


def _load_project(project_id: str) -> dict[str, object]:
    manager = get_project_manager()
    if not manager.project_exists(project_id):
        raise HTTPException(status_code=404, detail="project_not_found")
    return manager.load_project(project_id)


def _user_id(user: object) -> str:
    for key in ("id", "user_id", "username"):
        value = getattr(user, key, None)
        if value is not None:
            return str(value)
    return str(user)


def _json_value(value: str | None) -> object:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


async def _load_persisted_context(
    session: AsyncSession, *, project_id: str, user_id: str, body: CreativeContextRequest
) -> tuple[dict[str, object], list[object], dict[str, object], dict[str, object] | None]:
    board = await session.get(CreativeBoard, body.creative_board_id)
    if board is None or board.user_id != user_id:
        raise CreativeContextResolutionError(
            "creative_board_not_found", details={"creative_board_id": body.creative_board_id}
        )
    if board.project_id != project_id:
        raise CreativeContextResolutionError("creative_board_project_mismatch")
    items = (
        (await session.execute(select(CreativeBoardItem).where(CreativeBoardItem.board_id == board.id))).scalars().all()
    )
    board_payload = {"id": board.id, "project_id": board.project_id, "items": items}

    plan = await session.get(CreationPlanRecord, body.creation_plan_id)
    if plan is None or plan.user_id != user_id:
        raise CreativeContextResolutionError(
            "creation_plan_not_found", details={"creation_plan_id": body.creation_plan_id}
        )
    plan_payload: dict[str, object] = {
        "id": plan.id,
        "project_id": plan.project_id,
        "status": plan.status,
        "skill_id": plan.skill_id,
        "creation_skill_version_id": plan.creation_skill_version_id,
        "project_snapshot": _json_value(plan.project_snapshot_json),
        "resource_ids": _json_value(plan.resource_ids_json),
        "parameters": _json_value(plan.parameters_json),
        "preview_json": plan.preview_json,
        "estimated_cost": plan.estimated_cost,
        "previewed": plan.status in {"previewed", "confirmed", "started", "running", "succeeded"},
    }
    preview = _json_value(plan.preview_json)
    if isinstance(preview, dict):
        plan_payload.update(preview)

    run_payload: dict[str, object] | None = None
    if body.workflow_run_id:
        run = await session.get(WorkflowRun, body.workflow_run_id)
        if run is None or run.user_id != user_id:
            raise CreativeContextResolutionError(
                "workflow_run_not_found", details={"workflow_run_id": body.workflow_run_id}
            )
        if run.project_id != project_id:
            raise CreativeContextResolutionError("workflow_run_project_mismatch")
        run_payload = {
            "id": run.id,
            "project_id": run.project_id,
            "status": run.status,
            "error_code": getattr(run, "error_code", None),
        }
        revision = await session.get(WorkflowRevision, run.workflow_revision_id)
        if revision is not None:
            run_payload["generation_mode"] = revision.generation_mode
    return board_payload, list(items), plan_payload, run_payload


@router.post("/projects/{project_id}/creative-context/resolve")
async def resolve_context(
    project_id: str,
    body: CreativeContextRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    project = await asyncio.to_thread(_load_project, project_id)
    try:
        board, board_items, creation_plan, workflow_run = await _load_persisted_context(
            session, project_id=project_id, user_id=_user_id(current_user), body=body
        )
        return resolve_creation_context(
            project_id=project_id,
            project=project,
            selected_resources=[
                SelectedResource(id=resource.id, resource_type=resource.resource_type)
                for resource in body.selected_resources
            ],
            creative_board_id=body.creative_board_id,
            episode_id=body.episode_id,
            shot_id=body.shot_id,
            current_skill_id=body.current_skill_id,
            creation_plan_id=body.creation_plan_id,
            workflow_run_id=body.workflow_run_id,
            board=board,
            board_items=board_items,
            creation_plan=creation_plan,
            workflow_run=workflow_run,
            previewed=body.previewed,
            confirmed=body.confirmed,
            quality_gate_passed=body.quality_gate_passed,
            approval_status=body.approval_status,
            allow_gate_bypass=body.allow_gate_bypass,
            generation_mode=body.generation_mode,
            generation_mode_override=body.generation_mode_override,
            context_references=[
                ContextReference(text=item.text, expected_type=item.expected_type) for item in body.context_references
            ],
        )
    except CreativeContextResolutionError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, **exc.details}) from exc


@router.post("/projects/{project_id}/creative-context/resolve-references")
async def resolve_references(
    project_id: str,
    body: ContextReferenceResolutionRequest,
    current_user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    """Resolve natural-language context before a Creation Plan exists."""

    project = await asyncio.to_thread(_load_project, project_id)
    try:
        board = await session.get(CreativeBoard, body.creative_board_id)
        user_id = _user_id(current_user)
        if board is None or board.user_id != user_id:
            raise CreativeContextResolutionError(
                "creative_board_not_found", details={"creative_board_id": body.creative_board_id}
            )
        if board.project_id != project_id:
            raise CreativeContextResolutionError("creative_board_project_mismatch")
        items = (
            (await session.execute(select(CreativeBoardItem).where(CreativeBoardItem.board_id == board.id)))
            .scalars()
            .all()
        )
        return resolve_context_references(
            project_id=project_id,
            project=project,
            context_references=[
                ContextReference(text=item.text, expected_type=item.expected_type) for item in body.context_references
            ],
            selected_resources=[
                SelectedResource(id=item.id, resource_type=item.resource_type) for item in body.selected_resources
            ],
            board_items=list(items),
            episode_id=body.episode_id,
            shot_id=body.shot_id,
        )
    except CreativeContextResolutionError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, **exc.details}) from exc

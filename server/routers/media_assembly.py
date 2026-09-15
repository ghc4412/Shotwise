"""HTTP API for versioned media assembly plans.

This endpoint only stores and validates deterministic assembly intent. It does not
invoke FFmpeg, create render jobs, or mutate media files.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from lib.media_assembly.plan import AssemblyPlanValidationError
from server.auth import CurrentUser
from server.services import media_assembly as service

router = APIRouter()


class AssemblyDocumentRequest(BaseModel):
    source_snapshot: dict[str, Any]
    timeline: list[dict[str, Any]]
    audio: dict[str, Any] = Field(default_factory=dict)
    subtitle: dict[str, Any] = Field(default_factory=dict)
    packaging: dict[str, Any] = Field(default_factory=dict)
    output_profile: dict[str, Any] = Field(default_factory=lambda: {"format": "mp4"})


class AssemblyPlanCreateRequest(AssemblyDocumentRequest):
    name: str = Field(min_length=1, max_length=200)
    scope: str = Field(default="episode", min_length=1, max_length=32)
    episode_number: int | None = Field(default=None, ge=1)


class AssemblyPlanStatusRequest(BaseModel):
    status: str = Field(min_length=1, max_length=24)


class AssemblyPreviewConfirmRequest(BaseModel):
    revision_number: int = Field(ge=1)


class AssemblyStaleCheckRequest(BaseModel):
    source_snapshot: dict[str, Any]


def _validation_error(exc: AssemblyPlanValidationError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid_assembly_plan", "errors": exc.errors})


def _not_found(exc: service.AssemblyPlanNotFoundError) -> HTTPException:
    return HTTPException(status_code=404, detail="assembly_plan_not_found")


def _conflict(exc: service.AssemblyPlanConflictError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code}
    if exc.status is not None:
        detail["status"] = exc.status
    return HTTPException(status_code=409, detail=detail)


@router.post("/projects/{project_name}/assembly-plans", status_code=201)
async def create_assembly_plan(
    project_name: str,
    body: AssemblyPlanCreateRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.create_plan(
            session,
            user_id=user.id,
            project_name=project_name,
            name=body.name,
            scope=body.scope,
            episode_number=body.episode_number,
            source_snapshot=body.source_snapshot,
            timeline=body.timeline,
            audio=body.audio,
            subtitle=body.subtitle,
            packaging=body.packaging,
            output_profile=body.output_profile,
        )
    except AssemblyPlanValidationError as exc:
        raise _validation_error(exc) from exc


@router.get("/projects/{project_name}/assembly-plans")
async def list_assembly_plans(
    project_name: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, list[dict[str, Any]]]:
    return {"items": await service.list_plans(session, user_id=user.id, project_name=project_name)}


@router.get("/assembly-plans/{plan_id}")
async def get_assembly_plan(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.get_plan(session, plan_id, user_id=user.id)
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.AssemblyPlanConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/assembly-plans/{plan_id}/revisions")
async def create_assembly_plan_revision(
    plan_id: str,
    body: AssemblyDocumentRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.create_revision(
            session,
            plan_id,
            user_id=user.id,
            source_snapshot=body.source_snapshot,
            timeline=body.timeline,
            audio=body.audio,
            subtitle=body.subtitle,
            packaging=body.packaging,
            output_profile=body.output_profile,
        )
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.AssemblyPlanConflictError as exc:
        raise _conflict(exc) from exc
    except AssemblyPlanValidationError as exc:
        raise _validation_error(exc) from exc


@router.post("/assembly-plans/{plan_id}/status")
async def transition_assembly_plan(
    plan_id: str,
    body: AssemblyPlanStatusRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.transition_plan(session, plan_id, user_id=user.id, target_status=body.status)
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.AssemblyPlanConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/assembly-plans/{plan_id}/preview-confirm")
async def confirm_assembly_preview(
    plan_id: str,
    body: AssemblyPreviewConfirmRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.confirm_preview(
            session,
            plan_id,
            user_id=user.id,
            revision_number=body.revision_number,
        )
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.AssemblyPlanConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/assembly-plans/{plan_id}/render-confirm")
async def confirm_assembly_render(
    plan_id: str,
    body: AssemblyPreviewConfirmRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.confirm_render(
            session,
            plan_id,
            user_id=user.id,
            revision_number=body.revision_number,
        )
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.AssemblyPlanConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/assembly-plans/{plan_id}/stale-check")
async def check_assembly_plan_stale(
    plan_id: str,
    body: AssemblyStaleCheckRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.check_stale(
            session,
            plan_id,
            user_id=user.id,
            current_source_snapshot=body.source_snapshot,
        )
    except service.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc


__all__ = ["router"]

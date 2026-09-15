"""HTTP endpoints for queued low-resolution media assembly previews."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from server.auth import CurrentUser
from server.services import media_assembly
from server.services import media_rendering as service

router = APIRouter()


class PreviewRenderRequest(BaseModel):
    revision_number: int | None = Field(default=None, ge=1)
    max_attempts: int = Field(default=3, ge=1, le=10)


def _not_found(_: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail="render_resource_not_found")


def _conflict(exc: service.RenderRevisionConflictError | service.RenderJobConflictError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code}
    if exc.status is not None:
        detail["status"] = exc.status
    return HTTPException(status_code=409, detail=detail)


def _artifact_file_response(metadata: dict[str, Any], path) -> FileResponse:
    return FileResponse(path, media_type=metadata["mime_type"], filename=path.name)


def _not_ready(exc: service.FinalRenderNotReadyError) -> HTTPException:
    return HTTPException(status_code=409, detail={"code": "not_ready", "resource": str(exc)})


def _review_failure(exc: service.FinalRenderReviewError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": exc.code, "message": exc.message})


def _review_conflict(exc: service.RenderReviewConflictError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code}
    if exc.status is not None:
        detail["status"] = exc.status
    return HTTPException(status_code=409, detail=detail)


def _subtitle_error(exc: service.SubtitleExportError) -> HTTPException:
    return HTTPException(status_code=422, detail={"code": "invalid_subtitles", "message": str(exc)})


@router.post("/assembly-plans/{plan_id}/preview-renders", status_code=202)
async def create_preview_render(
    plan_id: str,
    body: PreviewRenderRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.create_preview_job(
            session,
            plan_id,
            user_id=user.id,
            revision_number=body.revision_number,
            max_attempts=body.max_attempts,
        )
        await session.commit()
    except (service.RenderRevisionConflictError, service.RenderJobConflictError) as exc:
        raise _conflict(exc) from exc
    except (service.RenderJobNotFoundError, media_assembly.AssemblyPlanNotFoundError) as exc:
        raise _not_found(exc) from exc
    background_tasks.add_task(service.run_preview_job_background, result["id"], user_id=user.id)
    return result


@router.post("/assembly-plans/{plan_id}/final-renders", status_code=202)
async def create_final_render(
    plan_id: str,
    body: PreviewRenderRequest,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.create_final_job(
            session,
            plan_id,
            user_id=user.id,
            revision_number=body.revision_number,
            max_attempts=body.max_attempts,
        )
        await session.commit()
    except (service.RenderRevisionConflictError, service.RenderJobConflictError) as exc:
        raise _conflict(exc) from exc
    except (service.RenderJobNotFoundError, media_assembly.AssemblyPlanNotFoundError) as exc:
        raise _not_found(exc) from exc
    background_tasks.add_task(service.run_final_job_background, result["id"], user_id=user.id)
    return result


@router.get("/assembly-plans/{plan_id}/final-renders")
async def list_final_renders(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, list[dict[str, Any]]]:
    try:
        return {"items": await service.list_render_jobs(session, plan_id, user_id=user.id, kind="final")}
    except (service.RenderJobNotFoundError, media_assembly.AssemblyPlanNotFoundError) as exc:
        raise _not_found(exc) from exc


@router.post("/render-jobs/{job_id}/final-retry", status_code=202)
async def retry_final_render(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.retry_final_job(session, job_id, user_id=user.id)
        await session.commit()
    except service.RenderJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except (service.RenderRevisionConflictError, service.RenderJobConflictError) as exc:
        raise _conflict(exc) from exc
    background_tasks.add_task(service.run_final_job_background, result["id"], user_id=user.id)
    return result


@router.get("/render-jobs/{job_id}")
async def get_preview_render(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.get_render_job(session, job_id, user_id=user.id)
    except service.RenderJobNotFoundError as exc:
        raise _not_found(exc) from exc


@router.get("/assembly-plans/{plan_id}/preview-renders")
async def list_preview_renders(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, list[dict[str, Any]]]:
    try:
        return {"items": await service.list_render_jobs(session, plan_id, user_id=user.id, kind="preview")}
    except (
        service.RenderJobNotFoundError,
        service.RenderArtifactNotFoundError,
        media_assembly.AssemblyPlanNotFoundError,
    ) as exc:
        raise _not_found(exc) from exc


@router.post("/render-jobs/{job_id}/retry", status_code=202)
async def retry_preview_render(
    job_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.retry_preview_job(session, job_id, user_id=user.id)
        await session.commit()
    except service.RenderJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except (service.RenderRevisionConflictError, service.RenderJobConflictError) as exc:
        raise _conflict(exc) from exc
    background_tasks.add_task(service.run_preview_job_background, result["id"], user_id=user.id)
    return result


@router.get("/assembly-plans/{plan_id}/final-review")
async def review_final_render(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.review_final_artifact(session, plan_id, user_id=user.id)
    except service.FinalRenderNotReadyError as exc:
        raise _not_ready(exc) from exc
    except service.FinalRenderReviewError as exc:
        raise _review_failure(exc) from exc
    except media_assembly.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/render-artifacts/{artifact_id}/review-confirm")
async def confirm_final_review(
    artifact_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.confirm_final_review(session, artifact_id, user_id=user.id)
    except service.RenderArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.RenderReviewConflictError as exc:
        raise _review_conflict(exc) from exc


@router.get("/assembly-plans/{plan_id}/subtitles")
async def export_assembly_subtitles(
    plan_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    format: str = Query(pattern="^(srt|vtt)$"),
) -> Response:
    try:
        result = await service.export_subtitles(session, plan_id, format=format, user_id=user.id)
    except service.SubtitleExportError as exc:
        raise _subtitle_error(exc) from exc
    except media_assembly.AssemblyPlanNotFoundError as exc:
        raise _not_found(exc) from exc
    response = Response(content=result["content"], media_type=result["media_type"])
    response.headers["Content-Disposition"] = f'attachment; filename="{result["filename"]}"'
    return response


@router.get("/render-artifacts/{artifact_id}/review-frames/{position}")
async def get_final_review_frame(
    artifact_id: str,
    position: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> FileResponse:
    try:
        metadata, path = await service.get_final_review_frame_file(
            session, artifact_id, position=position, user_id=user.id
        )
    except service.RenderArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
    return _artifact_file_response(metadata, path)


@router.get("/render-jobs/{job_id}/artifact")
async def get_preview_artifact_for_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> FileResponse:
    try:
        job = await service.get_render_job(session, job_id, user_id=user.id)
        artifact = job.get("artifact")
        if not artifact:
            raise service.RenderArtifactNotFoundError(job_id)
        metadata, path = await service.get_render_artifact_file(session, artifact["id"], user_id=user.id)
    except (
        service.RenderJobNotFoundError,
        service.RenderArtifactNotFoundError,
        media_assembly.AssemblyPlanNotFoundError,
    ) as exc:
        raise _not_found(exc) from exc
    return _artifact_file_response(metadata, path)


@router.get("/render-artifacts/{artifact_id}")
async def get_preview_artifact(
    artifact_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> FileResponse:
    try:
        metadata, path = await service.get_render_artifact_file(session, artifact_id, user_id=user.id)
    except service.RenderArtifactNotFoundError as exc:
        raise _not_found(exc) from exc
    return _artifact_file_response(metadata, path)


__all__ = ["router"]

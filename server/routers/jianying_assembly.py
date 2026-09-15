"""HTTP endpoint for immutable assembly-plan Jianying draft exports."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from server.auth import CurrentUser
from server.services import jianying_assembly_export as service
from server.services.media_assembly import AssemblyPlanConflictError, AssemblyPlanNotFoundError

router = APIRouter()


@router.get("/assembly-plans/{plan_id}/jianying-draft")
async def export_jianying_draft(
    plan_id: str,
    background_tasks: BackgroundTasks,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> FileResponse:
    try:
        bundle = await service.export_current_revision(session, plan_id, user_id=user.id)
    except AssemblyPlanNotFoundError as exc:
        raise HTTPException(status_code=404, detail="assembly_plan_not_found") from exc
    except AssemblyPlanConflictError as exc:
        raise HTTPException(status_code=409, detail={"code": exc.code, "status": exc.status}) from exc
    except service.JianyingExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail={"code": exc.code, "message": exc.message}) from exc
    background_tasks.add_task(bundle.cleanup)
    return FileResponse(
        bundle.path,
        media_type="application/zip",
        filename=bundle.path.name,
        background=background_tasks,
    )


__all__ = ["router"]

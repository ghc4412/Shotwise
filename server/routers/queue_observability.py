"""队列可观测性只读 API。

- ``GET /queue/observability`` —— 队列积压 / 位次 / 供应商 p50-p95 / 泳道占用 / 告警快照；
- ``GET /tasks/{task_id}/queue-position`` —— 单个任务在所属泳道里的排队名次。

两个端点只读，不含调度副作用（ADR 0007：孤儿任务不自动重排）。告警文案由调用方按
``code`` 本地化，本层不输出面向用户的自然语言。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from lib.api_errors import NotFoundError
from lib.db import get_async_session
from lib.queue_observability import build_snapshot, task_queue_position

router = APIRouter()


@router.get("/queue/observability")
async def get_queue_observability(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    project_name: str | None = Query(default=None),
):
    """返回队列诊断快照；未启动 worker 时省掉泳道与 ETA 容量分母。"""
    worker = getattr(request.app.state, "generation_worker", None)
    return await build_snapshot(session, worker=worker, project_name=project_name)


@router.get("/tasks/{task_id}/queue-position")
async def get_task_queue_position(
    task_id: str,
    session: AsyncSession = Depends(get_async_session),
):
    """返回任务排队名次（0 基）；任务不存在时 404。"""
    position = await task_queue_position(session, task_id)
    if position is None:
        raise NotFoundError("task_not_found", id=task_id)
    return position

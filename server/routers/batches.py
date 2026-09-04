"""Project-scoped API for durable generation batches."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from lib.db.repositories.generation_batch_repo import GenerationBatchRepository
from lib.generation_batches import (
    BatchAdmissionError,
    BatchNotFoundError,
    BatchOrchestrator,
    GenerationBatch,
    GenerationBatchItem,
    GenerationBatchRequest,
)
from lib.generation_queue import GenerationQueue, get_generation_queue
from server.auth import CurrentUser

router = APIRouter()


class BatchTaskRequest(BaseModel):
    """Queue task fields accepted from a batch client."""

    model_config = ConfigDict(extra="forbid")

    task_type: str = Field(min_length=1, max_length=128)
    media_type: str = Field(min_length=1, max_length=64)
    resource_id: str = Field(min_length=1, max_length=512)
    payload: dict[str, Any] | None = None
    script_file: str | None = Field(default=None, max_length=512)
    resource_type: str | None = Field(default=None, max_length=128)
    source: Literal["webui", "agent", "api"] = "webui"
    dependency_task_id: str | None = Field(default=None, max_length=128)
    dependency_group: str | None = Field(default=None, max_length=128)
    dependency_index: int | None = Field(default=None, ge=0)
    provider_id: str | None = Field(default=None, max_length=256)


class BatchItemRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    item_id: str = Field(min_length=1, max_length=128)
    task: BatchTaskRequest


class CreateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[BatchItemRequest] = Field(min_length=1, max_length=500)


def get_batch_queue() -> GenerationQueue:
    return get_generation_queue()


def _orchestrator(
    *,
    project_name: str,
    user_id: str,
    session: AsyncSession,
    queue: GenerationQueue,
) -> BatchOrchestrator:
    return BatchOrchestrator(
        repository=GenerationBatchRepository(session, user_id=user_id, project_name=project_name),
        tasks=queue.batch_adapter(project_name=project_name),
        user_id=user_id,
    )


async def _response(orchestrator: BatchOrchestrator, batch: GenerationBatch) -> dict[str, Any]:
    status = await orchestrator.get_status(batch.batch_id)
    tasks: list[dict[str, Any]] = []
    for item, task_id in zip(batch.items, batch.task_ids, strict=True):
        task = await orchestrator.get_task(task_id)
        tasks.append(
            {
                "item_id": item.item_id,
                "task_id": task_id,
                "status": str(task.get("status")) if task is not None else "failed",
            }
        )
    return {
        "batch_id": batch.batch_id,
        "project_name": batch.project_name,
        "status": status.value,
        "cancel_requested": batch.cancel_requested,
        "tasks": tasks,
    }


async def _load_response(orchestrator: BatchOrchestrator, batch_id: str) -> dict[str, Any]:
    try:
        batch = await orchestrator.get_batch(batch_id)
    except BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="batch_not_found") from exc
    return await _response(orchestrator, batch)


@router.post("/projects/{project_name}/batches", status_code=201)
async def create_batch(
    project_name: str,
    body: CreateBatchRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    queue: GenerationQueue = Depends(get_batch_queue),
) -> dict[str, Any]:
    orchestrator = _orchestrator(project_name=project_name, user_id=user.id, session=session, queue=queue)
    request = GenerationBatchRequest(
        project_name=project_name,
        items=tuple(
            GenerationBatchItem(item_id=item.item_id, task=item.task.model_dump(exclude_none=True))
            for item in body.items
        ),
    )
    try:
        batch = await orchestrator.admit(request)
    except (BatchAdmissionError, IntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="batch_admission_failed") from exc
    return await _response(orchestrator, batch)


@router.get("/projects/{project_name}/batches/{batch_id}")
async def get_batch(
    project_name: str,
    batch_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    queue: GenerationQueue = Depends(get_batch_queue),
) -> dict[str, Any]:
    orchestrator = _orchestrator(project_name=project_name, user_id=user.id, session=session, queue=queue)
    return await _load_response(orchestrator, batch_id)


@router.post("/projects/{project_name}/batches/{batch_id}/cancel")
async def cancel_batch(
    project_name: str,
    batch_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    queue: GenerationQueue = Depends(get_batch_queue),
) -> dict[str, Any]:
    orchestrator = _orchestrator(project_name=project_name, user_id=user.id, session=session, queue=queue)
    try:
        await orchestrator.cancel(batch_id)
    except BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="batch_not_found") from exc
    return await _load_response(orchestrator, batch_id)


@router.post("/projects/{project_name}/batches/{batch_id}/retry-failed")
async def retry_failed_batch(
    project_name: str,
    batch_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    queue: GenerationQueue = Depends(get_batch_queue),
) -> dict[str, Any]:
    orchestrator = _orchestrator(project_name=project_name, user_id=user.id, session=session, queue=queue)
    try:
        batch = await orchestrator.retry_failed(batch_id)
    except BatchNotFoundError as exc:
        raise HTTPException(status_code=404, detail="batch_not_found") from exc
    except (BatchAdmissionError, IntegrityError, ValueError) as exc:
        raise HTTPException(status_code=409, detail="batch_retry_failed") from exc
    return await _response(orchestrator, batch)

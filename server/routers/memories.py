"""Long-term Agent memory API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, Query
from pydantic import BaseModel, Field

from lib.api_errors import BadRequestError, NotFoundError
from lib.db import async_session_factory
from lib.project_manager import get_project_manager
from server.auth import CurrentUser
from server.services.memory_service import MemoryService

router = APIRouter()


class MemoryCreateRequest(BaseModel):
    category: str = Field(default="other", max_length=32)
    content: str
    source: str = Field(default="user", max_length=32)
    metadata: dict[str, Any] | None = None


class MemoryUpdateRequest(BaseModel):
    category: str | None = Field(default=None, max_length=32)
    content: str | None = None
    metadata: dict[str, Any] | None = None


class CandidateCreateRequest(BaseModel):
    scope: str
    project_name: str | None = None
    category: str = Field(default="other", max_length=32)
    content: str
    source_session_id: str | None = None
    source_message_id: str | None = None
    metadata: dict[str, Any] | None = None


class MemoryListResponse(BaseModel):
    items: list[dict[str, Any]]


class MemoryClearResponse(BaseModel):
    deleted: int


class MemoryImportRequest(BaseModel):
    user_memories: list[dict[str, Any]] | None = None
    project_memories: list[dict[str, Any]] | None = None
    entries: list[dict[str, Any]] | None = None


def _ensure_project(project_name: str) -> str:
    try:
        get_project_manager().get_project_path(project_name)
    except ValueError as exc:
        raise BadRequestError("invalid_project_name", name=project_name) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("project_not_found", name=project_name) from exc
    return project_name


def _service_context():
    return async_session_factory()


@router.get("/memories/user", response_model=MemoryListResponse)
async def list_user_memories(user: CurrentUser) -> MemoryListResponse:
    async with _service_context() as session:
        items = await MemoryService(session).list_memories(user_id=user.id, scope="user")
    return MemoryListResponse(items=items)


@router.post("/memories/user", status_code=201)
async def create_user_memory(body: MemoryCreateRequest, user: CurrentUser) -> dict[str, Any]:
    async with _service_context() as session:
        async with session.begin():
            item = await MemoryService(session).create_memory(
                user_id=user.id,
                scope="user",
                project_name=None,
                category=body.category,
                content=body.content,
                source=body.source,
                metadata=body.metadata,
            )
    return item


@router.delete("/memories/user", response_model=MemoryClearResponse)
async def clear_user_memories(user: CurrentUser) -> MemoryClearResponse:
    async with _service_context() as session:
        async with session.begin():
            deleted = await MemoryService(session).clear_memories(user_id=user.id, scope="user")
    return MemoryClearResponse(deleted=deleted)


@router.get("/projects/{project_name}/memories", response_model=MemoryListResponse)
async def list_project_memories(project_name: str, user: CurrentUser) -> MemoryListResponse:
    project_name = _ensure_project(project_name)
    async with _service_context() as session:
        items = await MemoryService(session).list_memories(user_id=user.id, scope="project", project_name=project_name)
    return MemoryListResponse(items=items)


@router.post("/projects/{project_name}/memories", status_code=201)
async def create_project_memory(project_name: str, body: MemoryCreateRequest, user: CurrentUser) -> dict[str, Any]:
    project_name = _ensure_project(project_name)
    async with _service_context() as session:
        async with session.begin():
            item = await MemoryService(session).create_memory(
                user_id=user.id,
                scope="project",
                project_name=project_name,
                category=body.category,
                content=body.content,
                source=body.source,
                metadata=body.metadata,
            )
    return item


@router.delete("/projects/{project_name}/memories", response_model=MemoryClearResponse)
async def clear_project_memories(project_name: str, user: CurrentUser) -> MemoryClearResponse:
    project_name = _ensure_project(project_name)
    async with _service_context() as session:
        async with session.begin():
            deleted = await MemoryService(session).clear_memories(
                user_id=user.id, scope="project", project_name=project_name
            )
    return MemoryClearResponse(deleted=deleted)


@router.patch("/memories/{memory_id}")
async def update_memory(memory_id: str, body: MemoryUpdateRequest, user: CurrentUser) -> dict[str, Any]:
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).update_memory(
                user_id=user.id,
                memory_id=memory_id,
                category=body.category,
                content=body.content,
                metadata=body.metadata,
            )


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, user: CurrentUser) -> None:
    async with _service_context() as session:
        async with session.begin():
            await MemoryService(session).delete_memory(user_id=user.id, memory_id=memory_id)


@router.get("/memory-candidates", response_model=MemoryListResponse)
async def list_memory_candidates(
    user: CurrentUser,
    scope: str | None = Query(default=None),
    project_name: str | None = Query(default=None),
) -> MemoryListResponse:
    if project_name is not None:
        project_name = _ensure_project(project_name)
    async with _service_context() as session:
        items = await MemoryService(session).list_candidates(user_id=user.id, scope=scope, project_name=project_name)
    return MemoryListResponse(items=items)


@router.post("/memory-candidates", status_code=201)
async def create_memory_candidate(body: CandidateCreateRequest, user: CurrentUser) -> dict[str, Any]:
    if body.project_name is not None:
        _ensure_project(body.project_name)
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).create_candidate(
                user_id=user.id,
                scope=body.scope,
                project_name=body.project_name,
                category=body.category,
                content=body.content,
                source_session_id=body.source_session_id,
                source_message_id=body.source_message_id,
                metadata=body.metadata,
            )


@router.post("/memory-candidates/{candidate_id}/accept")
async def accept_memory_candidate(candidate_id: str, user: CurrentUser) -> dict[str, Any]:
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).accept_candidate(user_id=user.id, candidate_id=candidate_id)


@router.post("/memory-candidates/{candidate_id}/reject")
async def reject_memory_candidate(candidate_id: str, user: CurrentUser) -> dict[str, Any]:
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).reject_candidate(user_id=user.id, candidate_id=candidate_id)


@router.get("/memories/export")
async def export_memories(
    user: CurrentUser,
    project_name: str | None = Query(default=None),
) -> dict[str, Any]:
    if project_name is not None:
        project_name = _ensure_project(project_name)
    async with _service_context() as session:
        return await MemoryService(session).export_memories(user_id=user.id, project_name=project_name)


@router.post("/memories/import")
async def import_memories(
    user: CurrentUser,
    body: MemoryImportRequest = Body(...),
    project_name: str | None = Query(default=None),
) -> dict[str, int]:
    if project_name is not None:
        project_name = _ensure_project(project_name)
    payload = body.model_dump(exclude_none=True)
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).import_memories(
                user_id=user.id, payload=payload, project_name=project_name
            )


@router.post("/projects/{project_name}/memories/import")
async def import_project_memories(
    project_name: str,
    user: CurrentUser,
    body: MemoryImportRequest = Body(...),
) -> dict[str, int]:
    project_name = _ensure_project(project_name)
    payload = body.model_dump(exclude_none=True)
    async with _service_context() as session:
        async with session.begin():
            return await MemoryService(session).import_project_memories(
                user_id=user.id, project_name=project_name, payload=payload
            )


__all__ = ["router"]

"""Semantic Creative Board API; execution remains in workflow endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from lib.feature_flags import feature_enabled
from server.auth import CurrentUser
from server.services import creative_boards as service


def _require_feature() -> None:
    if not feature_enabled("creative_board"):
        raise HTTPException(status_code=404, detail={"code": "feature_disabled", "feature": "creative_board"})


router = APIRouter(dependencies=[Depends(_require_feature)])


class BoardCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    viewport: dict[str, Any] = Field(default_factory=dict)
    display_settings: dict[str, Any] = Field(default_factory=dict)


class BoardUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    viewport: dict[str, Any] | None = None
    display_settings: dict[str, Any] | None = None
    expected_revision: int | None = Field(default=None, ge=1)


class BoardItemRequest(BaseModel):
    item_type: str = Field(min_length=1, max_length=32)
    resource_type: str = Field(min_length=1, max_length=32)
    resource_id: str = Field(min_length=1, max_length=256)
    position: dict[str, Any] = Field(default_factory=dict)
    size: dict[str, Any] = Field(default_factory=dict)
    group_id: str | None = Field(default=None, max_length=36)
    display_settings: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)


class BoardEdgeRequest(BaseModel):
    source_item_id: str = Field(min_length=1, max_length=36)
    target_item_id: str = Field(min_length=1, max_length=36)
    relation: str = Field(min_length=1, max_length=32)
    ordinal: int | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    expected_revision: int | None = Field(default=None, ge=1)


class BoardSnapshotItemRequest(BoardItemRequest):
    id: str | None = Field(default=None, min_length=1, max_length=36)
    expected_revision: int | None = Field(default=None, exclude=True)


class BoardSnapshotEdgeRequest(BoardEdgeRequest):
    id: str | None = Field(default=None, min_length=1, max_length=36)
    expected_revision: int | None = Field(default=None, exclude=True)


class BoardSnapshotRequest(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    viewport: dict[str, Any] = Field(default_factory=dict)
    display_settings: dict[str, Any] = Field(default_factory=dict)
    created_at: str | None = None
    items: list[BoardSnapshotItemRequest] = Field(default_factory=list)
    edges: list[BoardSnapshotEdgeRequest] = Field(default_factory=list)
    expected_revision: int = Field(ge=1)


class BoardVersionRequest(BaseModel):
    version_name: str = Field(min_length=1, max_length=200)
    expected_revision: int | None = Field(default=None, ge=1)


class BoardRestoreRequest(BaseModel):
    expected_revision: int = Field(ge=1)


class BoardCopyRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    version_id: str | None = Field(default=None, min_length=1, max_length=36)


def _not_found() -> HTTPException:
    return HTTPException(status_code=404, detail="creative_board_not_found")


def _conflict(exc: service.CreativeBoardConflictError) -> HTTPException:
    return HTTPException(
        status_code=409,
        detail={
            "code": "creative_board_revision_conflict",
            "current_revision": exc.current_revision,
            "current_updated_at": exc.current_updated_at.isoformat(),
        },
    )


@router.post("/projects/{project_id}/creative-boards")
async def create_board(
    project_id: str,
    body: BoardCreateRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.create_board(
            session,
            user_id=user.id,
            project_id=project_id,
            name=body.name,
            viewport=body.viewport,
            display_settings=body.display_settings,
        )
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/projects/{project_id}/creative-boards")
async def list_boards(project_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)):
    return await service.list_boards(session, user_id=user.id, project_id=project_id)


@router.get("/creative-boards/{board_id}")
async def get_board(board_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)):
    try:
        return await service.get_board(session, board_id, user_id=user.id)
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc


@router.put("/creative-boards/{board_id}/snapshot")
async def replace_snapshot(
    board_id: str,
    body: BoardSnapshotRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.replace_board_snapshot(
            session,
            board_id,
            user_id=user.id,
            snapshot=body.model_dump(mode="json", exclude={"expected_revision"}),
            expected_revision=body.expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/creative-boards/{board_id}/versions")
async def create_version(
    board_id: str,
    body: BoardVersionRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.create_version(
            session,
            board_id,
            user_id=user.id,
            version_name=body.version_name,
            expected_revision=body.expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/creative-boards/{board_id}/versions")
async def list_versions(board_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)):
    try:
        return await service.list_versions(session, board_id, user_id=user.id)
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc


@router.get("/creative-boards/{board_id}/versions/{version_id}")
async def get_version(
    board_id: str, version_id: str, user: CurrentUser, session: AsyncSession = Depends(get_async_session)
):
    try:
        return await service.get_version(session, board_id, version_id, user_id=user.id)
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc


@router.post("/creative-boards/{board_id}/versions/{version_id}/restore")
async def restore_version(
    board_id: str,
    version_id: str,
    body: BoardRestoreRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.restore_version(
            session,
            board_id,
            version_id,
            user_id=user.id,
            expected_revision=body.expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/creative-boards/{board_id}/copy")
async def copy_board(
    board_id: str,
    body: BoardCopyRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.copy_board(
            session,
            board_id,
            user_id=user.id,
            name=body.name,
            version_id=body.version_id,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.patch("/creative-boards/{board_id}")
async def update_board(
    board_id: str,
    body: BoardUpdateRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.update_board(
            session,
            board_id,
            user_id=user.id,
            name=body.name,
            viewport=body.viewport,
            display_settings=body.display_settings,
            expected_revision=body.expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/creative-boards/{board_id}/items")
async def add_item(
    board_id: str,
    body: BoardItemRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.add_item(session, board_id, user_id=user.id, **body.model_dump())
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/creative-boards/{board_id}/items/{item_id}")
async def delete_item(
    board_id: str,
    item_id: str,
    user: CurrentUser,
    expected_revision: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.delete_item(
            session,
            board_id,
            item_id,
            user_id=user.id,
            expected_revision=expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc


@router.patch("/creative-boards/{board_id}/items/{item_id}")
async def update_item(
    board_id: str,
    item_id: str,
    body: BoardItemRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.update_item(
            session,
            board_id,
            item_id,
            user_id=user.id,
            position=body.position,
            size=body.size,
            group_id=body.group_id,
            update_group_id="group_id" in body.model_fields_set,
            display_settings=body.display_settings,
            expected_revision=body.expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc


@router.delete("/creative-boards/{board_id}")
async def delete_board(
    board_id: str,
    user: CurrentUser,
    expected_revision: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.delete_board(
            session,
            board_id,
            user_id=user.id,
            expected_revision=expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/creative-boards/{board_id}/edges")
async def add_edge(
    board_id: str,
    body: BoardEdgeRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.add_edge(session, board_id, user_id=user.id, **body.model_dump())
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc
    except service.CreativeBoardValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/creative-boards/{board_id}/edges/{edge_id}")
async def delete_edge(
    board_id: str,
    edge_id: str,
    user: CurrentUser,
    expected_revision: int | None = Query(default=None, ge=1),
    session: AsyncSession = Depends(get_async_session),
):
    try:
        return await service.delete_edge(
            session,
            board_id,
            edge_id,
            user_id=user.id,
            expected_revision=expected_revision,
        )
    except service.CreativeBoardNotFoundError as exc:
        raise _not_found() from exc
    except service.CreativeBoardConflictError as exc:
        raise _conflict(exc) from exc

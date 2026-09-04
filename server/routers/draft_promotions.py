"""HTTP seam for the isolated Agent/Upload/Online-AI draft promotion flow."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from dataclasses import asdict
from typing import Any, Literal

from fastapi import APIRouter
from pydantic import BaseModel, Field

from lib.api_errors import BadRequestError, NotFoundError
from lib.project_manager import get_project_manager
from lib.script_structure_validator import validate_script_structure
from server.auth import CurrentUser
from server.draft_promotion import Draft, DraftPromotionService, DraftTarget, DraftValidationIssue, PromotionPreparation
from server.draft_promotion_repository import FileDraftPromotionRepository

router = APIRouter()

DraftOrigin = Literal["agent", "upload", "online_ai"]


class CreateDraftPromotionRequest(BaseModel):
    script_file: str = Field(min_length=1, max_length=512)
    content: dict[str, Any]


class UpdateDraftPromotionRequest(BaseModel):
    content: dict[str, Any]


class ConfirmDraftPromotionRequest(BaseModel):
    confirmation_token: str = Field(min_length=1, max_length=512)


def _validate_script_draft(content: object) -> Sequence[DraftValidationIssue]:
    """Apply Shotwise's structural script validator before a promotion can be prepared."""
    if not isinstance(content, dict):
        return (DraftValidationIssue("draft_not_object", "Draft content must be a JSON object."),)
    result = validate_script_structure(content)
    if result.valid:
        return ()
    return tuple(DraftValidationIssue("script_structure_invalid", message) for message in result.errors)


def _service() -> tuple[FileDraftPromotionRepository, DraftPromotionService]:
    project_manager = get_project_manager()
    repository = FileDraftPromotionRepository(project_manager)
    return repository, DraftPromotionService(repository, validator=_validate_script_draft)


def _draft_response(draft: Draft) -> dict[str, Any]:
    return {
        "draft_id": draft.id,
        "project_name": draft.target.project_name,
        "script_file": draft.target.script_file,
        "origin": draft.origin,
        "base_revision": draft.base_revision,
        "base_fingerprint": draft.base_fingerprint,
        "content": draft.content,
        "prepared": draft.prepared is not None,
        "status": draft.status,
    }


def _ensure_project_scope(draft: Draft, project_name: str) -> None:
    if draft.target.project_name != project_name:
        raise NotFoundError("draft_not_found", id=draft.id)


def _ensure_actor_scope(draft: Draft, user: CurrentUser) -> None:
    if draft.actor_id != user.id:
        raise NotFoundError("draft_not_found", id=draft.id)


async def _create_draft_promotion(
    project_name: str, body: CreateDraftPromotionRequest, user: CurrentUser, *, origin: DraftOrigin
) -> dict[str, Any]:
    """Create a reviewable complete-script draft with a server-owned origin."""
    repository, service = _service()

    def _create() -> Draft:
        return service.create(
            target=DraftTarget(project_name=project_name, script_file=body.script_file),
            content=body.content,
            origin=origin,
            actor_id=user.id,
        )

    try:
        draft = await asyncio.to_thread(_create)
    except FileNotFoundError as exc:
        raise NotFoundError("script_not_found", name=body.script_file) from exc
    except (ValueError, OSError) as exc:
        raise BadRequestError("request_invalid") from exc
    return _draft_response(draft)


@router.post("/projects/{project_name}/draft-promotions", status_code=201)
async def create_draft_promotion(
    project_name: str, body: CreateDraftPromotionRequest, user: CurrentUser
) -> dict[str, Any]:
    """Create an Agent-generated reviewable draft."""
    return await _create_draft_promotion(project_name, body, user, origin="agent")


@router.post("/projects/{project_name}/draft-promotions/upload", status_code=201)
async def create_uploaded_draft_promotion(
    project_name: str, body: CreateDraftPromotionRequest, user: CurrentUser
) -> dict[str, Any]:
    """Create a reviewable draft from a complete structured-script upload."""
    return await _create_draft_promotion(project_name, body, user, origin="upload")


@router.post("/projects/{project_name}/draft-promotions/online-ai", status_code=201)
async def create_online_ai_draft_promotion(
    project_name: str, body: CreateDraftPromotionRequest, user: CurrentUser
) -> dict[str, Any]:
    """Create a reviewable draft from online AI generation."""
    return await _create_draft_promotion(project_name, body, user, origin="online_ai")


@router.get("/projects/{project_name}/draft-promotions")
async def list_draft_promotions(project_name: str, user: CurrentUser, script_file: str | None = None) -> dict[str, Any]:
    repository, service = _service()

    if script_file is None:
        drafts = await asyncio.to_thread(repository.list_all, project_name, actor_id=user.id)
    else:
        drafts = await asyncio.to_thread(
            service.list_drafts,
            target=DraftTarget(project_name=project_name, script_file=script_file),
            actor_id=user.id,
        )
    return {"drafts": [_draft_response(draft) for draft in drafts]}


@router.get("/projects/{project_name}/draft-promotions/{draft_id}")
async def get_draft_promotion(project_name: str, draft_id: str, user: CurrentUser) -> dict[str, Any]:
    repository, _service_instance = _service()

    def _load() -> Draft | None:
        return repository.load_draft(draft_id, actor_id=user.id)

    draft = await asyncio.to_thread(_load)
    if draft is None:
        raise NotFoundError("draft_not_found", id=draft_id)
    _ensure_project_scope(draft, project_name)
    _ensure_actor_scope(draft, user)
    return _draft_response(draft)


@router.patch("/projects/{project_name}/draft-promotions/{draft_id}")
async def update_draft_promotion(
    project_name: str, draft_id: str, body: UpdateDraftPromotionRequest, user: CurrentUser
) -> dict[str, Any]:
    _repository, service = _service()

    def _update() -> Draft:
        draft = service.get_draft(draft_id, actor_id=user.id)
        _ensure_project_scope(draft, project_name)
        _ensure_actor_scope(draft, user)
        return service.update(draft_id, content=body.content, actor_id=user.id)

    try:
        draft = await asyncio.to_thread(_update)
    except KeyError as exc:
        raise NotFoundError("draft_not_found", id=draft_id) from exc
    except ValueError as exc:
        raise BadRequestError("request_invalid") from exc
    return _draft_response(draft)


@router.post("/projects/{project_name}/draft-promotions/{draft_id}/abandon")
async def abandon_draft_promotion(project_name: str, draft_id: str, user: CurrentUser) -> dict[str, Any]:
    _repository, service = _service()

    def _abandon() -> Draft:
        draft = service.get_draft(draft_id, actor_id=user.id)
        _ensure_project_scope(draft, project_name)
        _ensure_actor_scope(draft, user)
        return service.abandon(draft_id, actor_id=user.id)

    try:
        draft = await asyncio.to_thread(_abandon)
    except KeyError as exc:
        raise NotFoundError("draft_not_found", id=draft_id) from exc
    return _draft_response(draft)


@router.post("/projects/{project_name}/draft-promotions/{draft_id}/prepare")
async def prepare_draft_promotion(project_name: str, draft_id: str, user: CurrentUser) -> dict[str, Any]:
    repository, service = _service()

    def _prepare() -> tuple[Draft, PromotionPreparation]:
        draft = service.get_draft(draft_id, actor_id=user.id)
        _ensure_project_scope(draft, project_name)
        _ensure_actor_scope(draft, user)
        return draft, service.prepare_promotion(draft_id, actor_id=user.id)

    try:
        draft, preparation = await asyncio.to_thread(_prepare)
    except KeyError as exc:
        raise NotFoundError("draft_not_found", id=draft_id) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("script_not_found", name=draft_id) from exc

    return {
        **_draft_response(draft),
        "status": preparation.status,
        "validation_issues": [asdict(issue) for issue in preparation.validation_issues],
        "conflicts": [asdict(conflict) for conflict in preparation.conflicts],
        "auto_merged_paths": list(preparation.auto_merged_paths),
        "confirmation_token": preparation.confirmation_token,
        "preview_content": preparation.preview_content,
    }


@router.post("/projects/{project_name}/draft-promotions/{draft_id}/confirm")
async def confirm_draft_promotion(
    project_name: str, draft_id: str, body: ConfirmDraftPromotionRequest, user: CurrentUser
) -> dict[str, Any]:
    repository, service = _service()

    def _confirm() -> dict[str, Any]:
        draft = service.get_draft(draft_id, actor_id=user.id)
        _ensure_project_scope(draft, project_name)
        _ensure_actor_scope(draft, user)
        result = service.confirm_promotion(draft_id, confirmation_token=body.confirmation_token, actor_id=user.id)
        return {
            "status": result.status,
            "validation_issues": [asdict(issue) for issue in result.validation_issues],
            "promoted_revision": result.promoted_revision,
        }

    try:
        return await asyncio.to_thread(_confirm)
    except KeyError as exc:
        raise NotFoundError("draft_not_found", id=draft_id) from exc
    except FileNotFoundError as exc:
        raise NotFoundError("script_not_found", name=draft_id) from exc

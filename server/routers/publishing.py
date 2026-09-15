"""HTTP endpoints for platform-independent publish jobs."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import get_async_session
from server.auth import CurrentUser
from server.services import publishing as service
from server.services.publishing_events import emit_publish_job_event

router = APIRouter()


class CreatePublishRequest(BaseModel):
    """Publish destination and idempotency contract; confirmation is server-owned."""

    review_snapshot_id: str = Field(min_length=1, max_length=36)
    platform: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(min_length=1, max_length=128)
    account_id: str | None = Field(default=None, min_length=1, max_length=36)
    destination: dict[str, Any] = Field(default_factory=dict)
    max_attempts: int = Field(default=3, ge=1, le=10)


class CreatePublishingAccountRequest(BaseModel):
    """OAuth completion payload; access tokens are never returned by this API."""

    platform: str = Field(min_length=1, max_length=64)
    platform_account_id: str = Field(min_length=1, max_length=256)
    account_name: str = Field(min_length=1, max_length=256)
    access_token: str = Field(min_length=1)
    refresh_token: str | None = None
    avatar_url: str | None = None
    scopes: list[str] = Field(default_factory=list)
    token_expires_at: datetime | None = None


def _not_found(_: Exception) -> HTTPException:
    return HTTPException(status_code=404, detail="publish_resource_not_found")


def _conflict(exc: service.PublishConflictError) -> HTTPException:
    detail: dict[str, Any] = {"code": exc.code}
    if exc.status is not None:
        detail["status"] = exc.status
    return HTTPException(status_code=409, detail=detail)


def _unavailable(exc: Exception) -> HTTPException:
    return HTTPException(status_code=503, detail={"code": str(exc)})


@router.get("/publishing/platforms")
async def list_platforms() -> list[dict[str, object]]:
    return await service.list_platforms()


@router.get("/publishing/accounts")
async def list_accounts(
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> list[dict[str, Any]]:
    return await service.list_publishing_accounts(session, user_id=user.id)


@router.post("/publishing/accounts", status_code=status.HTTP_201_CREATED)
async def create_account(
    body: CreatePublishingAccountRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.create_publishing_account(
            session,
            user_id=user.id,
            platform=body.platform,
            platform_account_id=body.platform_account_id,
            account_name=body.account_name,
            access_token=body.access_token,
            refresh_token=body.refresh_token,
            avatar_url=body.avatar_url,
            scopes=body.scopes,
            token_expires_at=body.token_expires_at,
        )
        await session.commit()
        return result
    except service.PublishValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc


@router.delete("/publishing/accounts/{account_id}")
async def revoke_account(
    account_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.revoke_publishing_account(session, account_id, user_id=user.id)
        await session.commit()
        return result
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/render-artifacts/{artifact_id}/publish", status_code=202)
async def create_publish_job(
    artifact_id: str,
    body: CreatePublishRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        create_kwargs: dict[str, Any] = {
            "review_snapshot_id": body.review_snapshot_id,
            "platform": body.platform,
            "idempotency_key": body.idempotency_key,
            "destination": body.destination,
            "max_attempts": body.max_attempts,
            "user_id": user.id,
        }
        if body.account_id is not None:
            create_kwargs["account_id"] = body.account_id
        result = await service.create_publish_job(session, artifact_id, **create_kwargs)
        await session.commit()
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.PublishValidationError as exc:
        raise HTTPException(status_code=422, detail={"code": str(exc)}) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc
    return result


@router.get("/publish-jobs")
async def list_publish_jobs(
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> dict[str, Any]:
    return await service.list_publish_jobs(session, user_id=user.id, limit=limit, offset=offset)


@router.get("/publish-jobs/{job_id}")
async def get_publish_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        return await service.get_publish_job(session, job_id, user_id=user.id)
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc


@router.post("/publish-jobs/{job_id}/retry", status_code=202)
async def retry_publish_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.retry_publish_job(session, job_id, user_id=user.id)
        await session.commit()
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc
    return result


@router.post("/publish-jobs/{job_id}/cancel", status_code=202)
async def cancel_publish_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.cancel_publish_job(session, job_id, user_id=user.id)
        await session.commit()
        emit_publish_job_event(result["project_name"], result["id"], source="webui")
        return result
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc


@router.post("/publish-jobs/{job_id}/poll", status_code=202)
async def poll_publish_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.poll_publish_job(session, job_id, user_id=user.id, adapter=None)
        await session.commit()
        return result
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc
    except service.PublishAdapterUnavailableError as exc:
        raise _unavailable(exc) from exc


@router.post("/publish-jobs/{job_id}/retract", status_code=202)
async def retract_publish_job(
    job_id: str,
    user: CurrentUser,
    session: AsyncSession = Depends(get_async_session),
) -> dict[str, Any]:
    try:
        result = await service.retract_publish_job(session, job_id, user_id=user.id, adapter=None)
        await session.commit()
        return result
    except service.PublishJobNotFoundError as exc:
        raise _not_found(exc) from exc
    except service.PublishConflictError as exc:
        raise _conflict(exc) from exc
    except service.PublishAdapterUnavailableError as exc:
        raise _unavailable(exc) from exc


__all__ = ["router"]

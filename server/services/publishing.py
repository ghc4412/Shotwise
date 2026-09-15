"""Persistence and lifecycle service for platform-independent publishing."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Awaitable, Callable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.assembly_plan import AssemblyPlan, AssemblyPlanRevision
from lib.db.models.publish import PublishJob
from lib.db.models.publishing_account import PublishingAccount
from lib.db.models.render_job import RenderArtifact, RenderReviewSnapshot
from lib.db.repositories.assembly_plan_repository import AssemblyPlanRepository
from server.services.publishing_adapters import PublishStatus, get_platform_capabilities
from server.services.publishing_crypto import encrypt_secret

PUBLISH_STATUSES = frozenset(
    {
        "queued",
        "running",
        "succeeded",
        "failed",
        "validating",
        "uploading",
        "processing",
        "publish_pending",
        "publishing",
        "submitted",
        "published",
        "failed_retryable",
        "failed_needs_user_action",
        "expired",
        "canceled",
        "retract_pending",
        "retracting",
        "retracted",
        "retract_failed",
    }
)
_RETRYABLE_FAILURES = frozenset({"platform_adapter_not_connected", "timeout", "rate_limited", "server_error"})
_BACKOFF_SECONDS = (60, 300, 1800)


class PublishJobNotFoundError(LookupError):
    """Raised when a publish job or its owned resource is absent."""


class PublishConflictError(RuntimeError):
    """Raised when a publish request conflicts with an immutable binding or state."""

    def __init__(self, code: str, *, status: str | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status


class PublishValidationError(ValueError):
    """Raised when a publish request has invalid platform or destination data."""


class PublishAdapterUnavailableError(RuntimeError):
    """Raised because a real platform adapter is not connected."""


class PublishAdapterUserActionError(RuntimeError):
    """Raised when a platform requires user action before retrying."""


def _json(value: Mapping[str, Any]) -> str:
    return json.dumps(dict(value), ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _request_fingerprint(
    *, artifact_id: str, review_snapshot_id: str, platform: str, destination_json: str, max_attempts: int
) -> str:
    payload = f"{artifact_id}\n{review_snapshot_id}\n{platform}\n{destination_json}\n{max_attempts}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _payload(job: PublishJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "user_id": job.user_id,
        "plan_id": job.plan_id,
        "project_name": job.project_name,
        "artifact_id": job.artifact_id,
        "review_snapshot_id": job.review_snapshot_id,
        "account_id": job.account_id,
        "revision_number": job.revision_number,
        "source_fingerprint": job.source_fingerprint,
        "artifact_fingerprint": job.artifact_fingerprint,
        "platform": job.platform,
        "destination": json.loads(job.destination_json),
        "idempotency_key": job.idempotency_key,
        "status": job.status,
        "attempt": job.attempt,
        "max_attempts": job.max_attempts,
        "error_code": job.error_code,
        "error_message": job.error_message,
        "external_content_id": job.external_content_id,
        "external_status": job.external_status,
        "next_poll_at": job.next_poll_at.isoformat() if job.next_poll_at else None,
        "last_polled_at": job.last_polled_at.isoformat() if job.last_polled_at else None,
        "created_at": job.created_at.isoformat(),
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
        "updated_at": job.updated_at.isoformat(),
    }


def _account_payload(account: PublishingAccount) -> dict[str, Any]:
    try:
        scopes = json.loads(account.scopes_json)
    except json.JSONDecodeError:
        scopes = []
    return {
        "id": account.id,
        "user_id": account.user_id,
        "platform": account.platform,
        "platform_account_id": account.platform_account_id,
        "account_name": account.account_name,
        "avatar_url": account.avatar_url,
        "scopes": scopes,
        "encryption_key_version": account.encryption_key_version,
        "status": account.status,
        "token_expires_at": account.token_expires_at.isoformat() if account.token_expires_at else None,
        "last_refresh_at": account.last_refresh_at.isoformat() if account.last_refresh_at else None,
        "last_error_code": account.last_error_code,
        "created_at": account.created_at.isoformat(),
        "updated_at": account.updated_at.isoformat(),
    }


async def _owned_job(session: AsyncSession, job_id: str, user_id: str) -> PublishJob:
    job = await session.scalar(select(PublishJob).where(PublishJob.id == job_id, PublishJob.user_id == user_id))
    if job is None:
        raise PublishJobNotFoundError(job_id)
    return job


async def _owned_artifact(session: AsyncSession, artifact_id: str, user_id: str) -> RenderArtifact:
    artifact = await session.scalar(
        select(RenderArtifact).where(RenderArtifact.id == artifact_id, RenderArtifact.user_id == user_id)
    )
    if artifact is None:
        raise PublishJobNotFoundError(artifact_id)
    return artifact


async def _owned_account(session: AsyncSession, account_id: str, user_id: str) -> PublishingAccount:
    account = await session.scalar(
        select(PublishingAccount).where(PublishingAccount.id == account_id, PublishingAccount.user_id == user_id)
    )
    if account is None:
        raise PublishJobNotFoundError(account_id)
    return account


async def _current_revision(session: AsyncSession, plan: AssemblyPlan) -> AssemblyPlanRevision:
    revision = await AssemblyPlanRepository(session).get_current_revision(plan)
    if revision is None:
        raise PublishConflictError("current_revision_missing", status=plan.status)
    return revision


async def _validate_binding(
    session: AsyncSession,
    *,
    artifact: RenderArtifact,
    review_snapshot_id: str,
    user_id: str,
) -> tuple[AssemblyPlan, AssemblyPlanRevision, RenderReviewSnapshot]:
    plan = await session.scalar(
        select(AssemblyPlan).where(AssemblyPlan.id == artifact.plan_id, AssemblyPlan.user_id == user_id)
    )
    if plan is None:
        raise PublishJobNotFoundError(artifact.plan_id)
    if artifact.kind != "final":
        raise PublishConflictError("final_artifact_required", status=plan.status)
    revision = await _current_revision(session, plan)
    if artifact.revision_number != revision.version_number:
        raise PublishConflictError("revision_conflict", status=plan.status)
    snapshot = await session.scalar(
        select(RenderReviewSnapshot).where(
            RenderReviewSnapshot.id == review_snapshot_id,
            RenderReviewSnapshot.user_id == user_id,
        )
    )
    if snapshot is None:
        raise PublishJobNotFoundError(review_snapshot_id)
    if (
        snapshot.artifact_id != artifact.id
        or snapshot.plan_id != plan.id
        or snapshot.revision_number != revision.version_number
    ):
        raise PublishConflictError("review_binding_mismatch", status=plan.status)
    if snapshot.status != "ready":
        raise PublishConflictError("review_blocked", status=snapshot.status)
    if snapshot.confirmed_by != user_id or snapshot.confirmed_at is None:
        raise PublishConflictError("review_confirmation_required", status=snapshot.status)
    if snapshot.source_fingerprint != revision.source_fingerprint:
        raise PublishConflictError("source_fingerprint_mismatch", status=plan.status)
    if snapshot.artifact_fingerprint != artifact.fingerprint:
        raise PublishConflictError("artifact_fingerprint_mismatch", status=plan.status)
    return plan, revision, snapshot


def _normalize_platform(platform: str) -> str:
    normalized = platform.strip().lower()
    if not normalized or len(normalized) > 64:
        raise PublishValidationError("platform_invalid")
    return normalized


def _backoff(attempt: int) -> timedelta:
    return timedelta(seconds=_BACKOFF_SECONDS[min(max(attempt - 1, 0), len(_BACKOFF_SECONDS) - 1)])


def _failure_status(error_code: str) -> str:
    return "failed_retryable" if error_code in _RETRYABLE_FAILURES else "failed_needs_user_action"


async def list_platforms() -> list[dict[str, object]]:
    from dataclasses import asdict

    from server.services.publishing_adapters import list_platform_capabilities

    return [asdict(item) if not isinstance(item, dict) else item for item in list_platform_capabilities()]


async def list_publishing_accounts(session: AsyncSession, *, user_id: str) -> list[dict[str, Any]]:
    result = await session.scalars(
        select(PublishingAccount).where(PublishingAccount.user_id == user_id).order_by(PublishingAccount.created_at)
    )
    return [_account_payload(account) for account in result]


async def get_publishing_account(session: AsyncSession, account_id: str, *, user_id: str) -> dict[str, Any]:
    return _account_payload(await _owned_account(session, account_id, user_id))


async def create_publishing_account(
    session: AsyncSession,
    *,
    user_id: str,
    platform: str,
    platform_account_id: str,
    account_name: str,
    access_token: str,
    refresh_token: str | None = None,
    avatar_url: str | None = None,
    scopes: Sequence[str] = (),
    token_expires_at: Any = None,
) -> dict[str, Any]:
    platform = _normalize_platform(platform)
    if get_platform_capabilities(platform) is None:
        raise PublishValidationError("platform_not_supported")
    if not platform_account_id.strip() or not account_name.strip() or not access_token:
        raise PublishValidationError("account_fields_invalid")
    now = utc_now()
    account = PublishingAccount(
        id=str(uuid.uuid4()),
        user_id=user_id,
        platform=platform,
        platform_account_id=platform_account_id.strip(),
        account_name=account_name.strip(),
        avatar_url=avatar_url,
        encrypted_access_token=encrypt_secret(access_token),
        encrypted_refresh_token=encrypt_secret(refresh_token) if refresh_token else None,
        token_expires_at=token_expires_at,
        scopes_json=json.dumps(sorted(set(scopes)), ensure_ascii=False),
        encryption_key_version="v1",
        status="active",
        created_at=now,
        updated_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(account)
            await session.flush()
    except IntegrityError as exc:
        raise PublishConflictError("publishing_account_already_exists") from exc
    return _account_payload(account)


async def revoke_publishing_account(session: AsyncSession, account_id: str, *, user_id: str) -> dict[str, Any]:
    account = await _owned_account(session, account_id, user_id)
    account.status = "revoked"
    account.encrypted_access_token = None
    account.encrypted_refresh_token = None
    account.updated_at = utc_now()
    return _account_payload(account)


async def create_publish_job(
    session: AsyncSession,
    artifact_id: str,
    *,
    review_snapshot_id: str,
    platform: str,
    idempotency_key: str,
    user_id: str,
    destination: Mapping[str, Any] | None = None,
    max_attempts: int = 3,
    account_id: str | None = None,
) -> dict[str, Any]:
    platform = _normalize_platform(platform)
    idempotency_key = idempotency_key.strip()
    if not idempotency_key or len(idempotency_key) > 128:
        raise PublishValidationError("idempotency_key_invalid")
    if destination is None:
        destination = {}
    if not isinstance(destination, Mapping):
        raise PublishValidationError("destination_invalid")
    if max_attempts < 1 or max_attempts > 10:
        raise PublishValidationError("max_attempts_invalid")
    if account_id is not None:
        account = await _owned_account(session, account_id, user_id)
        if account.platform != platform:
            raise PublishConflictError("account_platform_mismatch", status=account.status)
        if account.status != "active":
            raise PublishConflictError("publishing_account_inactive", status=account.status)
    artifact = await _owned_artifact(session, artifact_id, user_id)
    plan, revision, snapshot = await _validate_binding(
        session, artifact=artifact, review_snapshot_id=review_snapshot_id, user_id=user_id
    )
    destination_json = _json(destination)
    fingerprint = _request_fingerprint(
        artifact_id=artifact.id,
        review_snapshot_id=snapshot.id,
        platform=platform,
        destination_json=destination_json,
        max_attempts=max_attempts,
    )
    existing = await session.scalar(
        select(PublishJob).where(PublishJob.user_id == user_id, PublishJob.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if existing.request_fingerprint != fingerprint:
            raise PublishConflictError("idempotency_key_reused", status=existing.status)
        return _payload(existing)
    now = utc_now()
    job = PublishJob(
        id=str(uuid.uuid4()),
        user_id=user_id,
        plan_id=plan.id,
        project_name=plan.project_name,
        artifact_id=artifact.id,
        review_snapshot_id=snapshot.id,
        account_id=account_id,
        revision_number=revision.version_number,
        source_fingerprint=revision.source_fingerprint,
        artifact_fingerprint=artifact.fingerprint,
        platform=platform,
        destination_json=destination_json,
        idempotency_key=idempotency_key,
        request_fingerprint=fingerprint,
        status="queued",
        attempt=0,
        max_attempts=max_attempts,
        created_at=now,
        updated_at=now,
    )
    try:
        async with session.begin_nested():
            session.add(job)
            await session.flush()
    except IntegrityError:
        existing = await session.scalar(
            select(PublishJob).where(PublishJob.user_id == user_id, PublishJob.idempotency_key == idempotency_key)
        )
        if existing is None:
            raise
        if existing.request_fingerprint != fingerprint:
            raise PublishConflictError("idempotency_key_reused", status=existing.status)
        return _payload(existing)
    return _payload(job)


async def get_publish_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    return _payload(await _owned_job(session, job_id, user_id))


async def list_publish_jobs(
    session: AsyncSession,
    *,
    user_id: str,
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    """Return the authenticated user's publish history in stable newest-first order."""
    safe_limit = max(1, min(limit, 100))
    safe_offset = max(0, offset)
    base = select(PublishJob).where(PublishJob.user_id == user_id)
    total = int(await session.scalar(select(func.count()).select_from(base.subquery())) or 0)
    result = await session.scalars(
        base.order_by(PublishJob.created_at.desc(), PublishJob.id.desc()).offset(safe_offset).limit(safe_limit)
    )
    return {
        "items": [_payload(job) for job in result],
        "total": total,
        "limit": safe_limit,
        "offset": safe_offset,
    }


async def retry_publish_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    if job.status not in {"failed", "failed_retryable", "retract_failed"}:
        raise PublishConflictError("retry_requires_failed", status=job.status)
    if job.attempt >= job.max_attempts:
        raise PublishConflictError("retry_limit_reached", status=job.status)
    artifact = await _owned_artifact(session, job.artifact_id, user_id)
    await _validate_binding(session, artifact=artifact, review_snapshot_id=job.review_snapshot_id, user_id=user_id)
    job.status = "queued"
    job.error_code = None
    job.error_message = None
    job.completed_at = None
    job.next_poll_at = None
    job.updated_at = utc_now()
    return _payload(job)


async def cancel_publish_job(session: AsyncSession, job_id: str, *, user_id: str) -> dict[str, Any]:
    """Cancel an active publish request without retracting external content."""
    job = await _owned_job(session, job_id, user_id)
    if job.status not in {
        "queued",
        "publishing",
        "submitted",
        "processing",
        "publish_pending",
        "failed_retryable",
    }:
        raise PublishConflictError("cancel_requires_active", status=job.status)
    now = utc_now()
    job.status = "canceled"
    job.error_code = "canceled_by_user"
    job.error_message = "canceled_by_user"
    job.next_poll_at = None
    job.worker_id = None
    job.lease_until = None
    job.completed_at = now
    job.updated_at = now
    return _payload(job)


async def run_publish_job(
    session: AsyncSession,
    job_id: str,
    *,
    user_id: str,
    adapter: Callable[[PublishJob], Awaitable[None]] | None = None,
) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    if job.status != "queued":
        raise PublishConflictError("run_requires_queued", status=job.status)
    artifact = await _owned_artifact(session, job.artifact_id, user_id)
    try:
        await _validate_binding(session, artifact=artifact, review_snapshot_id=job.review_snapshot_id, user_id=user_id)
        job.status = "publishing"
        job.attempt += 1
        job.started_at = utc_now()
        job.updated_at = utc_now()
        if adapter is None:
            raise PublishAdapterUnavailableError("platform_adapter_not_connected")
        await adapter(job)
    except PublishConflictError as exc:
        job.status = "failed"
        job.attempt += 1
        job.error_code = exc.code
        job.error_message = exc.code
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        return _payload(job)
    except PublishAdapterUserActionError as exc:
        job.status = "failed_needs_user_action"
        job.error_code = str(exc)
        job.error_message = str(exc)
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        return _payload(job)
    except Exception as exc:
        code = str(exc) if isinstance(exc, PublishAdapterUnavailableError) else "publish_failed"
        job.status = "failed"
        job.error_code = code
        job.error_message = str(exc)
        job.next_poll_at = utc_now() + _backoff(job.attempt)
        job.completed_at = utc_now()
        job.updated_at = utc_now()
        return _payload(job)
    job.status = "succeeded"
    job.external_status = "published"
    job.error_code = None
    job.error_message = None
    job.completed_at = utc_now()
    job.next_poll_at = None
    job.updated_at = utc_now()
    return _payload(job)


async def list_due_publish_jobs(session: AsyncSession, *, limit: int = 100) -> list[dict[str, Any]]:
    now = utc_now()
    result = await session.scalars(
        select(PublishJob)
        .where(
            PublishJob.status.in_({"submitted", "processing", "publish_pending"}),
            or_(PublishJob.next_poll_at.is_(None), PublishJob.next_poll_at <= now),
        )
        .order_by(PublishJob.next_poll_at, PublishJob.created_at)
        .limit(max(1, min(limit, 500)))
    )
    return [_payload(job) for job in result]


async def poll_publish_job(
    session: AsyncSession,
    job_id: str,
    *,
    user_id: str,
    adapter: Any,
) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    if job.status not in {"submitted", "processing", "publish_pending"}:
        raise PublishConflictError("poll_requires_submitted", status=job.status)
    if adapter is None:
        raise PublishAdapterUnavailableError("platform_adapter_not_connected")
    try:
        result: PublishStatus = await adapter.poll(job)
    except Exception as exc:
        job.error_code = "poll_failed"
        job.error_message = str(exc)
        job.status = "failed_retryable"
        job.next_poll_at = utc_now() + _backoff(max(job.attempt, 1))
        job.last_polled_at = utc_now()
        job.updated_at = utc_now()
        return _payload(job)
    job.external_status = result.external_status
    job.last_polled_at = utc_now()
    job.updated_at = utc_now()
    if result.published:
        job.status = "published"
        job.completed_at = utc_now()
        job.next_poll_at = None
    elif result.failed:
        job.status = "failed_retryable" if result.retryable else "failed_needs_user_action"
        job.error_code = result.error_code or "publish_failed"
        job.error_message = result.error_message
        job.completed_at = utc_now()
        job.next_poll_at = utc_now() + _backoff(max(job.attempt, 1)) if result.retryable else None
    else:
        job.status = "processing"
        job.next_poll_at = utc_now() + _backoff(max(job.attempt, 1))
    return _payload(job)


async def retract_publish_job(session: AsyncSession, job_id: str, *, user_id: str, adapter: Any) -> dict[str, Any]:
    job = await _owned_job(session, job_id, user_id)
    if job.status != "published":
        raise PublishConflictError("retract_requires_published", status=job.status)
    capabilities = get_platform_capabilities(job.platform)
    if capabilities is not None and not capabilities.supports_retract:
        raise PublishConflictError("platform_retract_not_supported", status=job.status)
    if adapter is None:
        raise PublishAdapterUnavailableError("platform_adapter_not_connected")
    job.status = "retracting"
    job.updated_at = utc_now()
    try:
        await adapter.retract(job)
    except Exception as exc:
        job.status = "retract_failed"
        job.error_code = "retract_failed"
        job.error_message = str(exc)
        job.updated_at = utc_now()
        return _payload(job)
    job.status = "retracted"
    job.external_status = "retracted"
    job.completed_at = utc_now()
    job.updated_at = utc_now()
    return _payload(job)


__all__ = [
    "PublishAdapterUnavailableError",
    "PublishAdapterUserActionError",
    "PublishConflictError",
    "PublishJobNotFoundError",
    "PublishValidationError",
    "cancel_publish_job",
    "create_publish_job",
    "create_publishing_account",
    "get_publish_job",
    "get_publishing_account",
    "list_publish_jobs",
    "list_due_publish_jobs",
    "list_platforms",
    "list_publishing_accounts",
    "poll_publish_job",
    "retract_publish_job",
    "revoke_publishing_account",
    "retry_publish_job",
    "run_publish_job",
]

"""Durable worker for platform-independent publishing jobs.

The worker deliberately owns only orchestration. Platform adapters are injected
and are the only layer allowed to perform platform calls. Database work is
committed before an adapter is called, so a slow or failing platform cannot
hold an open transaction.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable, Mapping
from contextlib import AbstractAsyncContextManager
from datetime import datetime, timedelta
from typing import Any, cast

from sqlalchemy import case, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db.base import utc_now
from lib.db.models.publish import PublishJob
from lib.db.repositories.publishing_repository import PublishingRepository
from server.services.publishing import (
    PublishAdapterUnavailableError,
    PublishAdapterUserActionError,
)
from server.services.publishing_adapters import PublishStatus, PublishSubmission

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
AdapterRegistry = Any
ClaimHook = Callable[..., Awaitable[PublishJob | str | None] | PublishJob | str | None]
JobUpdatedHook = Callable[[PublishJob], Awaitable[None] | None]

_CLAIMABLE_STATUSES = frozenset({"queued", "submitted", "processing", "publish_pending", "failed_retryable"})
_POLL_STATUSES = frozenset({"submitted", "processing", "publish_pending", "failed_retryable", "publishing"})
_PUBLISHED_EXTERNAL_STATUSES = frozenset({"published", "succeeded", "success", "complete", "completed"})
_PROCESSING_EXTERNAL_STATUSES = frozenset({"processing", "pending", "queued", "uploading"})
_BACKOFF_SECONDS = (60, 300, 1800)


class PublishingWorker:
    """Process queued and due publishing jobs with injectable dependencies.

    ``claim_next`` and ``claim_due`` may be supplied by a repository once the
    database has native lease columns. They receive the active session and
    keyword arguments ``worker_id``, ``lease_until`` and ``limit``. Without
    hooks, the worker uses a conditional SQL update that is safe for the
    current schema and remains useful for a single process.
    """

    def __init__(
        self,
        *,
        session_factory: SessionFactory,
        adapter_registry: AdapterRegistry | None = None,
        poll_interval: float = 2.0,
        batch_size: int = 10,
        lease_seconds: float = 60.0,
        worker_id: str | None = None,
        claim_next: ClaimHook | None = None,
        claim_due: ClaimHook | None = None,
        on_job_updated: JobUpdatedHook | None = None,
        stop_timeout: float = 10.0,
    ) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if stop_timeout <= 0:
            raise ValueError("stop_timeout must be positive")
        self._session_factory = session_factory
        self._adapter_registry = adapter_registry
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._lease_seconds = lease_seconds
        self.worker_id = worker_id or f"publishing-worker-{uuid.uuid4().hex}"
        self._claim_next_hook = claim_next
        self._claim_due_hook = claim_due
        self._on_job_updated = on_job_updated
        self._stop_timeout = stop_timeout
        self._stop_event = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    @property
    def task(self) -> asyncio.Task[None] | None:
        """Return the background task, primarily for lifecycle diagnostics."""

        return self._task

    async def start(self) -> None:
        """Start the worker loop; repeated calls are idempotent."""

        if self._task is not None and not self._task.done():
            return
        self._stop_event.clear()
        self._task = asyncio.create_task(self._run_loop(), name=self.worker_id)

    async def stop(self) -> None:
        """Stop the loop and wait for in-flight processing to finish briefly."""

        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._stop_timeout)
        except TimeoutError:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        finally:
            self._task = None

    async def run_once(self) -> int:
        """Process one bounded batch and return the number of claimed jobs."""

        claimed = 0
        for claim_kind in ("new", "due"):
            while claimed < self._batch_size:
                if self._stop_event.is_set():
                    return claimed
                job = await self._claim_job(claim_kind)
                if job is None:
                    break
                claimed += 1
                try:
                    if claim_kind == "due" and self._should_poll(job):
                        await self._poll_claimed(job)
                    else:
                        await self._submit_claimed(job)
                except Exception:
                    # A broken adapter or one malformed row must not stop the
                    # worker from handling the rest of the batch.
                    logger.exception("publishing job processing failed: %s", job.id)
                    await self._record_retryable_failure(job, "publish_worker_failed", "publishing worker failed")
        return claimed

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("publishing worker iteration failed")
                processed = 0
            if self._stop_event.is_set():
                break
            delay = 0 if processed else self._poll_interval
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _claim_job(self, claim_kind: str) -> PublishJob | None:
        hook = self._claim_next_hook if claim_kind == "new" else self._claim_due_hook
        lease_until = utc_now() + timedelta(seconds=self._lease_seconds)
        async with self._session_factory() as session:
            if hook is not None:
                claimed = await self._invoke_claim_hook(hook, session, lease_until)
                job = await self._resolve_claim_result(session, claimed)
                if job is None:
                    await self._rollback(session)
                    return None
                job = await self._normalize_hook_claim(session, job, claim_kind)
                if job is None:
                    await self._rollback(session)
                    return None
                await self._commit(session)
                return self._detach(job)

            repository = PublishingRepository(session)
            if claim_kind == "new":
                job = await repository.claim_next_publish_job(
                    worker_id=self.worker_id,
                    lease_until=lease_until,
                    limit=self._batch_size,
                )
            else:
                job = await repository.claim_due_publish_job(
                    worker_id=self.worker_id,
                    lease_until=lease_until,
                    limit=self._batch_size,
                )
            if job is None:
                await self._rollback(session)
                return None
            detached = self._detach(job)
            await self._commit(session)
            return detached

    async def _normalize_hook_claim(
        self,
        session: AsyncSession,
        job: PublishJob,
        claim_kind: str,
    ) -> PublishJob | None:
        """Normalize a repository claim before adapter work begins.

        A repository hook may atomically lease a row and return either the
        pre-claim state or the already-normalized ``publishing`` state. When it
        returns a pre-claim retryable state, the worker performs the remaining
        state transition while retaining the lease owner condition so attempt
        accounting cannot be skipped or applied twice.
        """

        if job.status == "publishing":
            if claim_kind == "due" and job.attempt >= job.max_attempts:
                return None
            if claim_kind != "due":
                return None
            original_status = job.status
        else:
            if job.status not in _CLAIMABLE_STATUSES:
                return None
            if claim_kind == "new" and job.attempt >= job.max_attempts:
                return None
            if claim_kind == "due" and job.status == "failed_retryable" and job.attempt >= job.max_attempts:
                return None
            original_status = job.status

        values: dict[str, Any] = {
            "status": "publishing",
            "updated_at": utc_now(),
        }
        if claim_kind == "new":
            values.update({"attempt": PublishJob.attempt + 1, "started_at": utc_now()})
        else:
            values["attempt"] = case(
                (PublishJob.status.in_({"failed_retryable", "publishing"}), PublishJob.attempt + 1),
                else_=PublishJob.attempt,
            )
        conditions: list[Any] = [PublishJob.id == job.id, PublishJob.status == original_status]
        self._add_owner_condition(conditions)
        result = await session.execute(update(PublishJob).where(*conditions).values(**values))
        if cast(Any, result).rowcount != 1:
            return None
        return await session.scalar(select(PublishJob).where(PublishJob.id == job.id))

    async def _submit_claimed(self, claimed_job: PublishJob) -> None:
        adapter = await self._resolve_adapter(claimed_job.platform)
        if adapter is None:
            await self._record_failure(
                claimed_job,
                status="failed_needs_user_action",
                code="platform_adapter_not_connected",
                message="official platform adapter is not connected",
            )
            return
        try:
            submission = await adapter.submit(claimed_job)
        except PublishAdapterUserActionError as exc:
            await self._record_failure(claimed_job, status="failed_needs_user_action", code=str(exc), message=str(exc))
        except PublishAdapterUnavailableError as exc:
            await self._record_retryable_failure(claimed_job, str(exc), str(exc))
        except Exception as exc:
            await self._record_retryable_failure(claimed_job, "publish_submit_failed", str(exc))
        else:
            await self._record_submission(claimed_job, submission)

    async def _poll_claimed(self, claimed_job: PublishJob) -> None:
        adapter = await self._resolve_adapter(claimed_job.platform)
        if adapter is None:
            await self._record_failure(
                claimed_job,
                status="failed_needs_user_action",
                code="platform_adapter_not_connected",
                message="official platform adapter is not connected",
            )
            return
        try:
            result: PublishStatus = await adapter.poll(claimed_job)
        except PublishAdapterUserActionError as exc:
            await self._record_failure(claimed_job, status="failed_needs_user_action", code=str(exc), message=str(exc))
        except Exception as exc:
            await self._record_retryable_failure(claimed_job, "publish_poll_failed", str(exc))
        else:
            await self._record_poll_result(claimed_job, result)

    async def _resolve_adapter(self, platform: str) -> Any | None:
        registry = self._adapter_registry
        if registry is None:
            return None
        if isinstance(registry, Mapping):
            adapter = registry.get(platform)
        elif hasattr(registry, "get_adapter"):
            adapter = registry.get_adapter(platform)
        elif hasattr(registry, "get"):
            adapter = registry.get(platform)
        elif callable(registry):
            adapter = registry(platform)
        else:
            adapter = None
        if inspect.isawaitable(adapter):
            return await adapter
        return adapter

    async def _record_submission(self, claimed_job: PublishJob, submission: PublishSubmission) -> None:
        status = str(submission.external_status or "submitted").strip().lower()
        if status in _PUBLISHED_EXTERNAL_STATUSES:
            await self._persist_update(
                claimed_job,
                status="published",
                external_content_id=submission.external_content_id,
                external_status=submission.external_status,
                completed_at=utc_now(),
                next_poll_at=None,
                error_code=None,
                error_message=None,
            )
            return
        next_status = "processing" if status in _PROCESSING_EXTERNAL_STATUSES else "submitted"
        await self._persist_update(
            claimed_job,
            status=next_status,
            external_content_id=submission.external_content_id,
            external_status=submission.external_status,
            next_poll_at=utc_now() + self._backoff(1),
            error_code=None,
            error_message=None,
        )

    async def _record_poll_result(self, claimed_job: PublishJob, result: PublishStatus) -> None:
        if result.published:
            values: dict[str, Any] = {
                "status": "published",
                "external_status": result.external_status,
                "completed_at": utc_now(),
                "next_poll_at": None,
                "error_code": None,
                "error_message": None,
                "last_polled_at": utc_now(),
            }
        elif result.failed:
            retryable = result.retryable and self._can_retry(claimed_job)
            values = {
                "status": "failed_retryable" if retryable else "failed_needs_user_action",
                "external_status": result.external_status,
                "completed_at": None if retryable else utc_now(),
                "next_poll_at": utc_now() + self._backoff(claimed_job.attempt) if retryable else None,
                "error_code": result.error_code or "publish_failed",
                "error_message": result.error_message,
                "last_polled_at": utc_now(),
            }
        else:
            values = {
                "status": "processing",
                "external_status": result.external_status,
                "next_poll_at": utc_now() + self._backoff(claimed_job.attempt),
                "last_polled_at": utc_now(),
            }
        await self._persist_update(claimed_job, **values)

    async def _record_retryable_failure(self, claimed_job: PublishJob, code: str, message: str) -> None:
        retryable = self._can_retry(claimed_job)
        await self._record_failure(
            claimed_job,
            status="failed_retryable" if retryable else "failed_needs_user_action",
            code=code,
            message=message,
            next_poll_at=utc_now() + self._backoff(claimed_job.attempt) if retryable else None,
            completed_at=None if retryable else utc_now(),
        )

    async def _record_failure(
        self,
        claimed_job: PublishJob,
        *,
        status: str,
        code: str,
        message: str,
        next_poll_at: datetime | None = None,
        completed_at: datetime | None = None,
    ) -> None:
        await self._persist_update(
            claimed_job,
            status=status,
            error_code=code,
            error_message=message,
            next_poll_at=next_poll_at,
            completed_at=completed_at,
        )

    async def _persist_update(self, claimed_job: PublishJob, **values: Any) -> None:
        async with self._session_factory() as session:
            repository = PublishingRepository(session)
            status = values.get("status")
            if status == "published":
                job = await repository.mark_publish_completed(
                    job_id=claimed_job.id,
                    worker_id=self.worker_id,
                    external_content_id=values.get("external_content_id"),
                    external_status=values.get("external_status", "published"),
                    last_polled_at=values.get("last_polled_at"),
                )
            elif status in {"submitted", "processing"} and "external_content_id" in values:
                job = await repository.mark_publish_submitted(
                    job_id=claimed_job.id,
                    worker_id=self.worker_id,
                    status=status,
                    external_content_id=values.get("external_content_id"),
                    external_status=values.get("external_status"),
                    next_poll_at=values.get("next_poll_at"),
                    error_code=values.get("error_code"),
                    error_message=values.get("error_message"),
                )
            elif status == "processing":
                job = await repository.mark_publish_processing(
                    job_id=claimed_job.id,
                    worker_id=self.worker_id,
                    external_status=values.get("external_status"),
                    next_poll_at=values.get("next_poll_at"),
                    last_polled_at=values.get("last_polled_at"),
                )
            elif status in {"failed_retryable", "failed_needs_user_action"}:
                job = await repository.mark_publish_failed(
                    job_id=claimed_job.id,
                    worker_id=self.worker_id,
                    status=status,
                    error_code=str(values.get("error_code") or "publish_failed"),
                    error_message=str(values.get("error_message") or ""),
                    next_poll_at=values.get("next_poll_at"),
                    completed_at=values.get("completed_at"),
                    external_status=values.get("external_status"),
                    last_polled_at=values.get("last_polled_at"),
                )
            else:
                job = await repository.release_publish_job_lease(
                    job_id=claimed_job.id,
                    worker_id=self.worker_id,
                )
            if job is None:
                await self._rollback(session)
                return
            await self._commit(session)
            await self._notify(self._detach(job))

    async def _notify(self, job: PublishJob) -> None:
        if self._on_job_updated is None:
            return
        result = self._on_job_updated(job)
        if inspect.isawaitable(result):
            await result

    async def _invoke_claim_hook(self, hook: ClaimHook, session: AsyncSession, lease_until: datetime) -> Any:
        result = hook(session, worker_id=self.worker_id, lease_until=lease_until, limit=self._batch_size)
        if inspect.isawaitable(result):
            return await result
        return result

    async def _resolve_claim_result(self, session: AsyncSession, claimed: PublishJob | str | None) -> PublishJob | None:
        if claimed is None:
            return None
        job_id = claimed.id if isinstance(claimed, PublishJob) else str(claimed)
        return await session.scalar(select(PublishJob).where(PublishJob.id == job_id))

    def _should_poll(self, job: PublishJob) -> bool:
        return bool(getattr(job, "external_content_id", None)) and job.status in _POLL_STATUSES | {"publishing"}

    def _can_retry(self, job: PublishJob) -> bool:
        return job.attempt < job.max_attempts

    @staticmethod
    def _backoff(attempt: int) -> timedelta:
        index = max(0, min(attempt, len(_BACKOFF_SECONDS) - 1))
        return timedelta(seconds=_BACKOFF_SECONDS[index])

    def _add_lease_values(self, values: dict[str, Any], lease_until: datetime | None) -> None:
        if hasattr(PublishJob, "worker_id"):
            values["worker_id"] = self.worker_id if lease_until is not None else None
        if hasattr(PublishJob, "lease_until"):
            values["lease_until"] = lease_until

    def _add_lease_conditions(self, conditions: list[Any]) -> None:
        if hasattr(PublishJob, "lease_until"):
            conditions.append(or_(PublishJob.lease_until.is_(None), PublishJob.lease_until <= utc_now()))

    def _add_owner_condition(self, conditions: list[Any]) -> None:
        if hasattr(PublishJob, "worker_id"):
            conditions.append(PublishJob.worker_id == self.worker_id)

    @staticmethod
    def _detach(job: PublishJob) -> PublishJob:
        return copy.copy(job)

    @staticmethod
    async def _commit(session: AsyncSession) -> None:
        await session.commit()

    @staticmethod
    async def _rollback(session: AsyncSession) -> None:
        rollback = getattr(session, "rollback", None)
        if rollback is not None:
            await rollback()


__all__ = ["PublishingWorker"]

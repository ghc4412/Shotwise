"""Durable persistence boundary for publishing worker state transitions."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from typing import Any

from sqlalchemy import case, or_, select, update

from lib.db.base import utc_now
from lib.db.models.publish import PublishJob
from lib.db.repositories.base import BaseRepository, rowcount

_CLAIMABLE_STATUSES = frozenset({"queued", "submitted", "processing", "publish_pending", "failed_retryable"})
_POLL_STATUSES = frozenset({"submitted", "processing", "publish_pending", "failed_retryable", "publishing"})


class PublishingRepository(BaseRepository):
    """Own publish-job SQL and keep worker orchestration storage-agnostic.

    Methods intentionally flush but never commit. The worker commits the lease
    transaction before calling an external adapter and commits each state
    transition independently.
    """

    async def claim_next_publish_job(
        self, *, worker_id: str, lease_until: datetime, limit: int = 1
    ) -> PublishJob | None:
        """Atomically claim one queued job for a worker lease."""
        return await self._claim(
            statuses={"queued"},
            worker_id=worker_id,
            lease_until=lease_until,
            limit=limit,
            claim_kind="new",
        )

    async def claim_due_publish_job(
        self, *, worker_id: str, lease_until: datetime, limit: int = 1
    ) -> PublishJob | None:
        """Atomically claim one due retry or external-status polling job."""
        return await self._claim(
            statuses=_POLL_STATUSES,
            worker_id=worker_id,
            lease_until=lease_until,
            limit=limit,
            claim_kind="due",
        )

    async def release_publish_job_lease(self, *, job_id: str, worker_id: str) -> PublishJob | None:
        """Release a lease without changing the job's business state."""
        return await self._update_owned(
            job_id,
            worker_id=worker_id,
            values={"worker_id": None, "lease_until": None, "updated_at": utc_now()},
        )

    async def mark_publish_submitted(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        external_content_id: str | None,
        external_status: str | None,
        next_poll_at: datetime | None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> PublishJob | None:
        """Persist a successful adapter submission and release its lease."""
        return await self._mark(
            job_id,
            worker_id=worker_id,
            values={
                "status": status,
                "external_content_id": external_content_id,
                "external_status": external_status,
                "next_poll_at": next_poll_at,
                "error_code": error_code,
                "error_message": error_message,
            },
        )

    async def mark_publish_processing(
        self,
        *,
        job_id: str,
        worker_id: str,
        external_status: str | None,
        next_poll_at: datetime | None,
        last_polled_at: datetime | None = None,
    ) -> PublishJob | None:
        """Persist a still-processing external publication and release its lease."""
        return await self._mark(
            job_id,
            worker_id=worker_id,
            values={
                "status": "processing",
                "external_status": external_status,
                "next_poll_at": next_poll_at,
                "last_polled_at": last_polled_at,
            },
        )

    async def mark_publish_failed(
        self,
        *,
        job_id: str,
        worker_id: str,
        status: str,
        error_code: str,
        error_message: str,
        next_poll_at: datetime | None,
        completed_at: datetime | None,
        external_status: str | None = None,
        last_polled_at: datetime | None = None,
    ) -> PublishJob | None:
        """Persist a retryable or terminal failure and release its lease."""
        return await self._mark(
            job_id,
            worker_id=worker_id,
            values={
                "status": status,
                "error_code": error_code,
                "error_message": error_message,
                "next_poll_at": next_poll_at,
                "completed_at": completed_at,
                **({"external_status": external_status} if external_status is not None else {}),
                **({"last_polled_at": last_polled_at} if last_polled_at is not None else {}),
            },
        )

    async def mark_publish_completed(
        self,
        *,
        job_id: str,
        worker_id: str,
        external_content_id: str | None = None,
        external_status: str | None = "published",
        last_polled_at: datetime | None = None,
    ) -> PublishJob | None:
        """Persist a published terminal state and release its lease."""
        values: dict[str, Any] = {
            "status": "published",
            "external_status": external_status,
            "completed_at": utc_now(),
            "next_poll_at": None,
            "error_code": None,
            "error_message": None,
        }
        if external_content_id is not None:
            values["external_content_id"] = external_content_id
        if last_polled_at is not None:
            values["last_polled_at"] = last_polled_at
        return await self._mark(job_id, worker_id=worker_id, values=values)

    async def _claim(
        self,
        *,
        statuses: Iterable[str],
        worker_id: str,
        lease_until: datetime,
        limit: int,
        claim_kind: str,
    ) -> PublishJob | None:
        now = utc_now()
        conditions: list[Any] = [PublishJob.status.in_(statuses)]
        if claim_kind == "new":
            conditions.append(PublishJob.attempt < PublishJob.max_attempts)
        conditions.extend([or_(PublishJob.next_poll_at.is_(None), PublishJob.next_poll_at <= now)])
        conditions.append(or_(PublishJob.lease_until.is_(None), PublishJob.lease_until <= now))
        if claim_kind == "due":
            conditions.append(
                or_(
                    ~PublishJob.status.in_({"failed_retryable", "publishing"}),
                    PublishJob.attempt < PublishJob.max_attempts,
                )
            )
        # PostgreSQL workers skip rows leased by a competing transaction instead of waiting on the same candidate.
        # SQLite ignores FOR UPDATE and keeps the conditional UPDATE below as its concurrency guard.
        candidate = await self.session.scalar(
            select(PublishJob.id)
            .where(*conditions)
            .order_by(PublishJob.next_poll_at, PublishJob.created_at, PublishJob.id)
            .limit(max(1, min(limit, 500)))
            .with_for_update(skip_locked=True)
        )
        if candidate is None:
            return None
        values: dict[str, Any] = {
            "status": "publishing",
            "worker_id": worker_id,
            "lease_until": lease_until,
            "updated_at": now,
        }
        if claim_kind == "new":
            values.update({"attempt": PublishJob.attempt + 1, "started_at": now})
        else:
            values["attempt"] = case(
                (PublishJob.status.in_({"failed_retryable", "publishing"}), PublishJob.attempt + 1),
                else_=PublishJob.attempt,
            )
        result = await self.session.execute(
            update(PublishJob).where(PublishJob.id == candidate, *conditions).values(**values)
        )
        if rowcount(result) != 1:
            return None
        return await self.session.scalar(select(PublishJob).where(PublishJob.id == candidate))

    async def _mark(self, job_id: str, *, worker_id: str, values: dict[str, Any]) -> PublishJob | None:
        values = dict(values)
        values.update({"worker_id": None, "lease_until": None, "updated_at": utc_now()})
        return await self._update_owned(job_id, worker_id=worker_id, values=values)

    async def _update_owned(self, job_id: str, *, worker_id: str, values: dict[str, Any]) -> PublishJob | None:
        conditions = [PublishJob.id == job_id, PublishJob.worker_id == worker_id]
        result = await self.session.execute(update(PublishJob).where(*conditions).values(**values))
        if rowcount(result) != 1:
            return None
        return await self.session.scalar(select(PublishJob).where(PublishJob.id == job_id))


__all__ = ["PublishingRepository"]

"""Durable persistence boundary for render worker leases and cancellation."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import or_, select, update

from lib.db.base import utc_now
from lib.db.models.render_job import RenderJob
from lib.db.repositories.base import BaseRepository, rowcount

_IN_FLIGHT_STATUSES = ("running", "cancelling")


class RenderRepository(BaseRepository):
    """Own render-job SQL so worker orchestration stays storage-agnostic.

    Methods flush but never commit. The worker commits the claim before it
    starts ffmpeg and commits each lease or terminal transition independently.
    """

    async def list_claimable_jobs(self, *, limit: int = 10) -> list[RenderJob]:
        """Return queued jobs with attempts left and no worker lease, oldest first."""
        result = await self.session.scalars(
            select(RenderJob)
            .where(
                RenderJob.status == "queued",
                RenderJob.attempt < RenderJob.max_attempts,
                RenderJob.worker_id.is_(None),
            )
            .order_by(RenderJob.created_at, RenderJob.id)
            .limit(max(1, min(limit, 500)))
        )
        return list(result.all())

    async def pulse(self, *, job_id: str, worker_id: str, progress: float, stage: str) -> bool:
        """Refresh a running job's lease and progress; False means the lease was lost."""
        now = utc_now()
        result = await self.session.execute(
            update(RenderJob)
            .where(
                RenderJob.id == job_id,
                RenderJob.worker_id == worker_id,
                RenderJob.status.in_(_IN_FLIGHT_STATUSES),
            )
            .values(
                heartbeat_at=now,
                progress=max(0.0, min(1.0, progress)),
                progress_stage=stage,
                updated_at=now,
            )
        )
        return rowcount(result) == 1

    async def is_cancel_requested(self, *, job_id: str, worker_id: str) -> bool:
        """Return True when the owning worker must stop its media process."""
        value = await self.session.scalar(
            select(RenderJob.cancel_requested_at).where(
                RenderJob.id == job_id,
                RenderJob.worker_id == worker_id,
            )
        )
        return value is not None

    async def request_cancel(self, *, job_id: str, user_id: str) -> RenderJob | None:
        """Flag a queued or running job for cancellation without racing its worker."""
        now = utc_now()
        result = await self.session.execute(
            update(RenderJob)
            .where(
                RenderJob.id == job_id,
                RenderJob.user_id == user_id,
                RenderJob.status.in_(("queued", "running")),
            )
            .values(status="cancelling", cancel_requested_at=now, updated_at=now)
        )
        if rowcount(result) != 1:
            return None
        return await self.session.scalar(select(RenderJob).where(RenderJob.id == job_id))

    async def finalize_unclaimed_cancellation(self, *, job_id: str) -> bool:
        """Move an ownerless cancelling job straight to cancelled."""
        now = utc_now()
        result = await self.session.execute(
            update(RenderJob)
            .where(
                RenderJob.id == job_id,
                RenderJob.status == "cancelling",
                RenderJob.worker_id.is_(None),
            )
            .values(status="cancelled", progress_stage="cancelled", completed_at=now, updated_at=now)
        )
        return rowcount(result) == 1

    async def list_unclaimed_cancellations(self, *, limit: int = 50) -> list[RenderJob]:
        """Return cancelling jobs that no worker owns, oldest first."""
        result = await self.session.scalars(
            select(RenderJob)
            .where(RenderJob.status == "cancelling", RenderJob.worker_id.is_(None))
            .order_by(RenderJob.updated_at, RenderJob.id)
            .limit(max(1, min(limit, 500)))
        )
        return list(result.all())

    async def reclaim_stale_jobs(self, *, stale_before: datetime) -> int:
        """Settle jobs whose worker stopped reporting progress.

        A stale ``cancelling`` job honours the persisted request and lands in
        ``cancelled``; a stale ``running`` job returns to the queue unless it
        already burned every attempt, in which case it fails loudly.
        """
        now = utc_now()
        stale = await self.session.scalars(
            select(RenderJob).where(
                RenderJob.status.in_(_IN_FLIGHT_STATUSES),
                RenderJob.worker_id.is_not(None),
                or_(RenderJob.heartbeat_at.is_(None), RenderJob.heartbeat_at < stale_before),
            )
        )
        reclaimed = 0
        for job in stale.all():
            if job.status == "cancelling":
                job.status = "cancelled"
                job.error_code = None
                job.error_message = None
                job.completed_at = now
            elif job.attempt >= job.max_attempts:
                job.status = "failed"
                job.error_code = "render_worker_lost"
                job.error_message = "render worker stopped reporting progress"
                job.completed_at = now
            else:
                job.status = "queued"
                job.error_code = None
                job.error_message = None
            job.worker_id = None
            job.heartbeat_at = None
            job.progress_stage = job.status
            job.updated_at = now
            reclaimed += 1
        return reclaimed


__all__ = ["RenderRepository"]

"""Durable worker for assembly render jobs.

Scheduling, leasing, and terminal-state persistence live here; media work is
delegated to ``server.services.media_rendering``. Each claim is a conditional
update, ffmpeg runs under a refreshed heartbeat lease, and a persisted
cancellation request stops the media process cooperatively.
"""

from __future__ import annotations

import asyncio
import copy
import inspect
import logging
import uuid
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager, suppress
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from lib.db import async_session_factory
from lib.db.base import utc_now
from lib.db.models.render_job import RenderJob
from lib.db.repositories.render_repository import RenderRepository
from server.services.media_rendering import RenderJobConflictError, run_final_job, run_preview_job

logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
JobUpdatedHook = Callable[[RenderJob], Awaitable[None] | None]


class RenderWorker:
    """Process queued render jobs with a heartbeat lease and cancellation."""

    def __init__(
        self,
        *,
        session_factory: SessionFactory | None = None,
        poll_interval: float = 2.0,
        batch_size: int = 2,
        stale_after_seconds: float = 180.0,
        worker_id: str | None = None,
        on_job_updated: JobUpdatedHook | None = None,
        stop_timeout: float = 10.0,
    ) -> None:
        if poll_interval < 0:
            raise ValueError("poll_interval must be non-negative")
        if batch_size < 1:
            raise ValueError("batch_size must be positive")
        if stale_after_seconds <= 0:
            raise ValueError("stale_after_seconds must be positive")
        if stop_timeout <= 0:
            raise ValueError("stop_timeout must be positive")
        self._session_factory: SessionFactory = session_factory or async_session_factory
        self._poll_interval = poll_interval
        self._batch_size = batch_size
        self._stale_after_seconds = stale_after_seconds
        self.worker_id = worker_id or f"render-worker-{uuid.uuid4().hex}"
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
        """Signal the loop to stop and wait for the in-flight job to unwind."""

        task = self._task
        if task is None:
            return
        self._stop_event.set()
        try:
            await asyncio.wait_for(asyncio.shield(task), timeout=self._stop_timeout)
        except TimeoutError:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        finally:
            self._task = None

    async def run_once(self) -> int:
        """Reclaim expired leases, drain ownerless cancellations, then claim a batch."""

        if self._stop_event.is_set():
            return 0
        await self._reclaim_stale()
        await self._finalize_unclaimed_cancellations()
        async with self._session_factory() as session:
            repository = RenderRepository(session)
            jobs = await repository.list_claimable_jobs(limit=self._batch_size)
            detached = [self._detach(job) for job in jobs]
        claimed = 0
        for job in detached:
            if self._stop_event.is_set():
                break
            claimed += 1
            await self._process_job(job)
        return claimed

    async def _run_loop(self) -> None:
        while not self._stop_event.is_set():
            try:
                processed = await self.run_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("render worker iteration failed")
                processed = 0
            if self._stop_event.is_set():
                break
            delay = 0 if processed else self._poll_interval
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=delay)
            except TimeoutError:
                pass

    async def _process_job(self, job: RenderJob) -> None:
        job_id = job.id
        user_id = job.user_id
        kind = job.kind
        state: dict[str, Any] = {"progress": 0.0, "stage": "preparing"}

        async def on_progress(stage: str, fraction: float) -> None:
            state["progress"] = fraction
            state["stage"] = stage
            await self._pulse_progress(job_id, fraction, stage)

        async def cancel_check() -> bool:
            return await self._is_cancel_requested(job_id)

        heartbeat = asyncio.create_task(self._heartbeat_loop(job_id, state), name=f"{self.worker_id}:{job_id}")
        try:
            async with self._session_factory() as session:
                if kind == "final":
                    await run_final_job(
                        session,
                        job_id,
                        user_id=user_id,
                        worker_id=self.worker_id,
                        on_progress=on_progress,
                        cancel_check=cancel_check,
                    )
                else:
                    await run_preview_job(
                        session,
                        job_id,
                        user_id=user_id,
                        worker_id=self.worker_id,
                        on_progress=on_progress,
                        cancel_check=cancel_check,
                    )
        except RenderJobConflictError:
            # Losing the claim is expected when another worker reclaimed a stale
            # lease or the row moved on before this process started rendering.
            logger.info("render job claim skipped: %s", job_id)
        except Exception:
            logger.exception("render job execution failed: %s", job_id)
        finally:
            heartbeat.cancel()
            with suppress(asyncio.CancelledError):
                await heartbeat
            await self._notify_latest(job_id)

    async def _heartbeat_loop(self, job_id: str, state: dict[str, Any]) -> None:
        interval = max(1.0, self._stale_after_seconds / 3)
        while True:
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                return
            except TimeoutError:
                pass
            await self._pulse_progress(job_id, float(state["progress"]), str(state["stage"]))

    async def _pulse_progress(self, job_id: str, progress: float, stage: str) -> None:
        try:
            async with self._session_factory() as session:
                repository = RenderRepository(session)
                await repository.pulse(job_id=job_id, worker_id=self.worker_id, progress=progress, stage=stage)
                await session.commit()
        except Exception:
            logger.exception("render lease pulse failed: %s", job_id)

    async def _is_cancel_requested(self, job_id: str) -> bool:
        try:
            async with self._session_factory() as session:
                repository = RenderRepository(session)
                return await repository.is_cancel_requested(job_id=job_id, worker_id=self.worker_id)
        except Exception:
            logger.exception("render cancellation check failed: %s", job_id)
            return False

    async def _reclaim_stale(self) -> None:
        stale_before = utc_now() - timedelta(seconds=self._stale_after_seconds)
        try:
            async with self._session_factory() as session:
                repository = RenderRepository(session)
                reclaimed = await repository.reclaim_stale_jobs(stale_before=stale_before)
                if reclaimed:
                    await session.commit()
                else:
                    await session.rollback()
        except Exception:
            logger.exception("render lease reclaim failed")

    async def _finalize_unclaimed_cancellations(self) -> None:
        finalized_ids: list[str] = []
        try:
            async with self._session_factory() as session:
                repository = RenderRepository(session)
                jobs = await repository.list_unclaimed_cancellations(limit=self._batch_size * 5)
                for job in jobs:
                    if await repository.finalize_unclaimed_cancellation(job_id=job.id):
                        finalized_ids.append(job.id)
                if finalized_ids:
                    await session.commit()
                else:
                    await session.rollback()
        except Exception:
            logger.exception("render cancellation finalize failed")
            return
        for job_id in finalized_ids:
            await self._notify_latest(job_id)

    async def _notify_latest(self, job_id: str) -> None:
        if self._on_job_updated is None:
            return
        async with self._session_factory() as session:
            job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id))
        if job is None:
            return
        result = self._on_job_updated(self._detach(job))
        if inspect.isawaitable(result):
            await result

    @staticmethod
    def _detach(job: RenderJob) -> RenderJob:
        return copy.copy(job)


__all__ = ["RenderWorker"]

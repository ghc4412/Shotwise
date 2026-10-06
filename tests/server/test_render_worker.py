from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import event, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from lib.db.base import Base, utc_now
from lib.db.models.render_job import RenderJob
from server.services import render_worker as render_worker_module
from server.services.media_rendering import RenderJobConflictError
from server.services.render_worker import RenderWorker

pytestmark = [pytest.mark.integration, pytest.mark.sqlite_only]


@pytest.fixture()
async def render_session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'render.db'}")

    @event.listens_for(engine.sync_engine, "connect")
    def _set_sqlite_pragma(dbapi_conn: Any, _connection_record: Any) -> None:
        cursor = dbapi_conn.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.close()

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _job(
    job_id: str,
    *,
    status: str = "queued",
    kind: str = "preview",
    attempt: int = 0,
    max_attempts: int = 3,
    worker_id: str | None = None,
    heartbeat_at: datetime | None = None,
    cancel_requested_at: datetime | None = None,
) -> RenderJob:
    now = utc_now()
    return RenderJob(
        id=job_id,
        plan_id=f"plan-{job_id}",
        project_name="demo",
        user_id="user-1",
        revision_number=1,
        kind=kind,
        status=status,
        attempt=attempt,
        max_attempts=max_attempts,
        input_fingerprint=f"fingerprint-{job_id}",
        progress=0.0,
        progress_stage=status,
        worker_id=worker_id,
        heartbeat_at=heartbeat_at,
        cancel_requested_at=cancel_requested_at,
        created_at=now,
        updated_at=now,
    )


async def _seed(factory, *jobs: RenderJob) -> None:
    async with factory() as session:
        session.add_all(list(jobs))
        await session.commit()


async def _read_job(factory, job_id: str) -> RenderJob:
    async with factory() as session:
        job = await session.scalar(select(RenderJob).where(RenderJob.id == job_id))
        assert job is not None
        return job


RunHook = Callable[..., Awaitable[None]]


def _install_claiming_runner(monkeypatch: pytest.MonkeyPatch, *, run: RunHook | None = None) -> list[dict[str, Any]]:
    """Replace the job runners with an atomic claim mirroring the real service.

    ``run_preview_job`` and ``run_final_job`` claim a queued, unowned row with a
    conditional ``UPDATE``. The stand-in keeps that contract so worker
    orchestration can be exercised without a plan, a revision, or ffmpeg.
    """
    claimed: list[dict[str, Any]] = []

    async def _runner(
        session: AsyncSession,
        job_id: str,
        *,
        user_id: str,
        worker_id: str | None = None,
        on_progress: Any = None,
        cancel_check: Any = None,
    ) -> dict[str, Any]:
        now = utc_now()
        result = await session.execute(
            update(RenderJob)
            .where(RenderJob.id == job_id, RenderJob.status == "queued", RenderJob.worker_id.is_(None))
            .values(
                status="running",
                attempt=RenderJob.attempt + 1,
                worker_id=worker_id,
                heartbeat_at=now,
                started_at=now,
                progress_stage="preparing",
                updated_at=now,
            )
        )
        if int(getattr(result, "rowcount", 0) or 0) != 1:
            await session.rollback()
            raise RenderJobConflictError("job_claim_conflict", status="running")
        await session.commit()
        claimed.append({"job_id": job_id, "worker_id": worker_id})
        if run is not None:
            await run(job_id=job_id, worker_id=worker_id, on_progress=on_progress, cancel_check=cancel_check)
        return {"id": job_id}

    monkeypatch.setattr(render_worker_module, "run_preview_job", _runner)
    monkeypatch.setattr(render_worker_module, "run_final_job", _runner)
    return claimed


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"poll_interval": -1}, "poll_interval must be non-negative"),
        ({"batch_size": 0}, "batch_size must be positive"),
        ({"stale_after_seconds": 0}, "stale_after_seconds must be positive"),
        ({"stop_timeout": 0}, "stop_timeout must be positive"),
    ],
)
def test_constructor_rejects_invalid_tuning(kwargs: dict[str, Any], message: str) -> None:
    with pytest.raises(ValueError, match=message):
        RenderWorker(**kwargs)


async def test_two_workers_only_one_claims_the_job(render_session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _install_claiming_runner(monkeypatch)
    await _seed(render_session_factory, _job("job-1"))

    first = RenderWorker(session_factory=render_session_factory, worker_id="worker-1")
    second = RenderWorker(session_factory=render_session_factory, worker_id="worker-2")
    await asyncio.gather(first.run_once(), second.run_once())

    stored = await _read_job(render_session_factory, "job-1")
    assert len(claimed) == 1
    assert stored.status == "running"
    assert stored.worker_id in {"worker-1", "worker-2"}
    assert stored.attempt == 1


async def test_expired_running_lease_returns_to_the_queue(render_session_factory) -> None:
    await _seed(
        render_session_factory,
        _job(
            "job-1",
            status="running",
            attempt=1,
            worker_id="worker-1",
            heartbeat_at=utc_now() - timedelta(seconds=600),
        ),
    )

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-2")
    await worker._reclaim_stale()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "queued"
    assert stored.worker_id is None
    assert stored.heartbeat_at is None
    assert stored.progress_stage == "queued"


async def test_stale_running_job_fails_once_attempts_are_spent(render_session_factory) -> None:
    await _seed(
        render_session_factory,
        _job(
            "job-1",
            status="running",
            attempt=3,
            max_attempts=3,
            worker_id="worker-1",
            heartbeat_at=utc_now() - timedelta(seconds=600),
        ),
    )

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-2")
    await worker._reclaim_stale()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "failed"
    assert stored.error_code == "render_worker_lost"
    assert stored.worker_id is None
    assert stored.completed_at is not None


async def test_stale_cancelling_job_settles_as_cancelled(render_session_factory) -> None:
    await _seed(
        render_session_factory,
        _job(
            "job-1",
            status="cancelling",
            attempt=1,
            worker_id="worker-1",
            heartbeat_at=utc_now() - timedelta(seconds=600),
            cancel_requested_at=utc_now() - timedelta(seconds=600),
        ),
    )

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-2")
    await worker._reclaim_stale()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "cancelled"
    assert stored.error_code is None
    assert stored.worker_id is None
    assert stored.completed_at is not None


async def test_fresh_running_lease_is_left_alone(render_session_factory) -> None:
    await _seed(
        render_session_factory,
        _job("job-1", status="running", attempt=1, worker_id="worker-1", heartbeat_at=utc_now()),
    )

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-2")
    await worker._reclaim_stale()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "running"
    assert stored.worker_id == "worker-1"


async def test_ownerless_cancellation_is_settled_and_notified(render_session_factory) -> None:
    await _seed(render_session_factory, _job("job-1", status="cancelling", cancel_requested_at=utc_now()))
    seen: list[str] = []

    async def on_updated(job: RenderJob) -> None:
        seen.append(job.id)

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-1", on_job_updated=on_updated)
    processed = await worker.run_once()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "cancelled"
    assert stored.worker_id is None
    assert stored.completed_at is not None
    assert seen == ["job-1"]
    assert processed == 0


async def test_processed_job_publishes_progress_and_notifies(
    render_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    seen: list[tuple[str, str]] = []

    async def run(**kwargs: Any) -> None:
        await kwargs["on_progress"]("rendering_video", 0.5)

    _install_claiming_runner(monkeypatch, run=run)
    await _seed(render_session_factory, _job("job-1"))

    worker = RenderWorker(
        session_factory=render_session_factory,
        worker_id="worker-1",
        on_job_updated=lambda job: seen.append((job.id, job.status)),
    )
    await worker.run_once()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.progress == pytest.approx(0.5)
    assert stored.progress_stage == "rendering_video"
    assert seen == [("job-1", "running")]


async def test_cancel_check_reads_the_persisted_request(
    render_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    observed: list[bool] = []

    async def run(**kwargs: Any) -> None:
        observed.append(await kwargs["cancel_check"]())
        async with render_session_factory() as session:
            await session.execute(
                update(RenderJob)
                .where(RenderJob.id == "job-1")
                .values(status="cancelling", cancel_requested_at=utc_now(), updated_at=utc_now())
            )
            await session.commit()
        observed.append(await kwargs["cancel_check"]())

    _install_claiming_runner(monkeypatch, run=run)
    await _seed(render_session_factory, _job("job-1"))

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-1")
    await worker.run_once()

    assert observed == [False, True]


async def test_heartbeat_refreshes_the_lease_during_a_slow_job(
    render_session_factory, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def run(**kwargs: Any) -> None:
        await asyncio.sleep(1.4)

    _install_claiming_runner(monkeypatch, run=run)
    await _seed(render_session_factory, _job("job-1"))

    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-1", stale_after_seconds=3.0)
    await worker.run_once()

    stored = await _read_job(render_session_factory, "job-1")
    assert stored.started_at is not None
    assert stored.heartbeat_at is not None
    assert stored.heartbeat_at > stored.started_at


async def test_start_is_idempotent_and_stop_clears_the_task(render_session_factory) -> None:
    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-1", poll_interval=1.0)
    await worker.start()
    first = worker.task
    await worker.start()

    assert worker.task is first

    await worker.stop()
    assert worker.task is None


async def test_run_once_is_a_no_op_after_stop(render_session_factory, monkeypatch: pytest.MonkeyPatch) -> None:
    claimed = _install_claiming_runner(monkeypatch)
    worker = RenderWorker(session_factory=render_session_factory, worker_id="worker-1", poll_interval=1.0)
    await worker.start()
    await worker.stop()
    await _seed(render_session_factory, _job("job-1"))

    assert await worker.run_once() == 0
    assert claimed == []
    stored = await _read_job(render_session_factory, "job-1")
    assert stored.status == "queued"

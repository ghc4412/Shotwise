from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.db.base import Base, utc_now
from lib.db.models.publish import PublishJob
from server.services.publishing_adapters import PublishStatus, PublishSubmission
from server.services.publishing_worker import PublishingWorker

pytestmark = [pytest.mark.integration, pytest.mark.sqlite_only]


@dataclass
class FakeAdapter:
    submission: PublishSubmission = field(
        default_factory=lambda: PublishSubmission(external_content_id="external-1", external_status="submitted")
    )
    poll_result: PublishStatus = field(
        default_factory=lambda: PublishStatus(external_status="published", published=True)
    )
    submit_calls: list[str] = field(default_factory=list)
    poll_calls: list[str] = field(default_factory=list)
    submit_error: Exception | None = None

    async def submit(self, job: PublishJob) -> PublishSubmission:
        self.submit_calls.append(job.id)
        if self.submit_error is not None:
            raise self.submit_error
        return self.submission

    async def poll(self, job: PublishJob) -> PublishStatus:
        self.poll_calls.append(job.id)
        return self.poll_result


@pytest.fixture()
async def publish_session_factory(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'publish.db'}")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield factory
    await engine.dispose()


def _job(job_id: str, *, status: str = "queued", external_content_id: str | None = None) -> PublishJob:
    now = utc_now()
    return PublishJob(
        id=job_id,
        user_id="user-1",
        plan_id=f"plan-{job_id}",
        project_name="demo",
        artifact_id=f"artifact-{job_id}",
        review_snapshot_id=f"review-{job_id}",
        revision_number=1,
        source_fingerprint="source-fingerprint",
        artifact_fingerprint="artifact-fingerprint",
        platform="douyin",
        destination_json="{}",
        idempotency_key=f"key-{job_id}",
        request_fingerprint=f"request-{job_id}",
        status=status,
        attempt=1 if status != "queued" else 0,
        max_attempts=3,
        external_content_id=external_content_id,
        external_status="processing" if external_content_id else None,
        next_poll_at=now - timedelta(seconds=1) if external_content_id else None,
        created_at=now,
        updated_at=now,
    )


async def _read_job(factory, job_id: str) -> PublishJob:
    async with factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == job_id))
        assert job is not None
        return job


async def test_two_workers_only_one_claims_a_queued_job(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1"))
        await session.commit()

    first = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-1")
    second = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-2")
    claimed = await asyncio.gather(first._claim_job("new"), second._claim_job("new"))

    assert sum(job is not None for job in claimed) == 1
    stored = await _read_job(publish_session_factory, "job-1")
    assert stored.status == "publishing"
    assert stored.worker_id in {"worker-1", "worker-2"}
    assert stored.lease_until is not None


async def test_expired_publishing_lease_can_be_recovered(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1"))
        await session.commit()

    first = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-1", lease_seconds=1)
    claimed = await first._claim_job("new")
    assert claimed is not None

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.lease_until = utc_now() - timedelta(seconds=1)
        await session.commit()

    second = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-2")
    recovered = await second._claim_job("due")

    assert recovered is not None
    assert recovered.worker_id == "worker-2"
    assert recovered.status == "publishing"
    assert recovered.attempt == 2


async def test_queued_job_at_attempt_limit_is_not_claimed(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        job = _job("job-1")
        job.attempt = job.max_attempts
        session.add(job)
        await session.commit()

    worker = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-1")

    assert await worker._claim_job("new") is None
    stored = await _read_job(publish_session_factory, "job-1")
    assert stored.status == "queued"
    assert stored.attempt == stored.max_attempts


async def test_expired_publishing_lease_at_attempt_limit_is_not_recovered(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        job = _job("job-1")
        job.status = "publishing"
        job.attempt = job.max_attempts
        job.worker_id = "worker-1"
        job.lease_until = utc_now() - timedelta(seconds=1)
        session.add(job)
        await session.commit()

    worker = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-2")

    assert await worker._claim_job("due") is None
    stored = await _read_job(publish_session_factory, "job-1")
    assert stored.status == "publishing"
    assert stored.attempt == stored.max_attempts
    assert stored.worker_id == "worker-1"


async def test_expired_publishing_lease_recovery_stops_at_attempt_limit(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        job = _job("job-1")
        job.status = "publishing"
        job.attempt = job.max_attempts - 1
        job.worker_id = "worker-1"
        job.lease_until = utc_now() - timedelta(seconds=1)
        session.add(job)
        await session.commit()

    first_recovery = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-2")
    recovered = await first_recovery._claim_job("due")

    assert recovered is not None
    assert recovered.attempt == recovered.max_attempts

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.lease_until = utc_now() - timedelta(seconds=1)
        await session.commit()

    second_recovery = PublishingWorker(session_factory=publish_session_factory, worker_id="worker-3")
    assert await second_recovery._claim_job("due") is None
    stored = await _read_job(publish_session_factory, "job-1")
    assert stored.attempt == stored.max_attempts


async def test_run_once_submits_and_persists_async_submission(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1"))
        await session.commit()

    adapter = FakeAdapter()
    worker = PublishingWorker(
        session_factory=publish_session_factory,
        adapter_registry={"douyin": adapter},
        batch_size=1,
    )

    assert await worker.run_once() == 1
    job = await _read_job(publish_session_factory, "job-1")
    assert job.status == "submitted"
    assert job.external_content_id == "external-1"
    assert adapter.submit_calls == ["job-1"]


async def test_retryable_attempts_are_incremented_and_bounded(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        job = _job("job-1", status="failed_retryable")
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        session.add(job)
        await session.commit()

    adapter = FakeAdapter(submit_error=RuntimeError("temporary failure"))
    worker = PublishingWorker(
        session_factory=publish_session_factory,
        adapter_registry={"douyin": adapter},
        batch_size=1,
    )

    assert await worker.run_once() == 1
    job = await _read_job(publish_session_factory, "job-1")
    assert job.attempt == 2
    assert job.status == "failed_retryable"

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once() == 1
    job = await _read_job(publish_session_factory, "job-1")
    assert job.attempt == 3
    assert job.status == "failed_needs_user_action"

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once() == 0
    assert adapter.submit_calls == ["job-1", "job-1"]


async def test_repository_claim_hook_preserves_attempt_limit(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        job = _job("job-1", status="failed_retryable")
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        session.add(job)
        await session.commit()

    adapter = FakeAdapter(submit_error=RuntimeError("temporary failure"))

    async def claim_due(session, *, worker_id, lease_until, limit):
        del limit
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        if job is None or job.status != "failed_retryable" or job.next_poll_at is None:
            return None
        await session.execute(
            update(PublishJob)
            .where(PublishJob.id == job.id, PublishJob.status == "failed_retryable")
            .values(worker_id=worker_id, lease_until=lease_until)
        )
        return job.id

    worker = PublishingWorker(
        session_factory=publish_session_factory,
        adapter_registry={"douyin": adapter},
        claim_due=claim_due,
        batch_size=1,
    )

    assert await worker.run_once() == 1
    job = await _read_job(publish_session_factory, "job-1")
    assert job.attempt == 2
    assert job.status == "failed_retryable"

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once() == 1
    job = await _read_job(publish_session_factory, "job-1")
    assert job.attempt == 3
    assert job.status == "failed_needs_user_action"

    async with publish_session_factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == "job-1"))
        assert job is not None
        job.next_poll_at = utc_now() - timedelta(seconds=1)
        await session.commit()

    assert await worker.run_once() == 0
    assert adapter.submit_calls == ["job-1", "job-1"]


async def test_run_once_marks_direct_submission_as_published(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1"))
        await session.commit()

    adapter = FakeAdapter(submission=PublishSubmission(external_content_id="external-1", external_status="published"))
    worker = PublishingWorker(session_factory=publish_session_factory, adapter_registry={"douyin": adapter})

    await worker.run_once()
    job = await _read_job(publish_session_factory, "job-1")
    assert job.status == "published"
    assert job.completed_at is not None
    assert job.next_poll_at is None


async def test_run_once_safely_fails_without_connected_adapter(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1"))
        await session.commit()

    worker = PublishingWorker(session_factory=publish_session_factory, adapter_registry={})

    await worker.run_once()
    job = await _read_job(publish_session_factory, "job-1")
    assert job.status == "failed_needs_user_action"
    assert job.error_code == "platform_adapter_not_connected"


async def test_run_once_polls_due_job(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add(_job("job-1", status="processing", external_content_id="external-1"))
        await session.commit()

    adapter = FakeAdapter()
    worker = PublishingWorker(session_factory=publish_session_factory, adapter_registry={"douyin": adapter})

    await worker.run_once()
    job = await _read_job(publish_session_factory, "job-1")
    assert job.status == "published"
    assert adapter.poll_calls == ["job-1"]


async def test_one_adapter_failure_does_not_stop_next_job(publish_session_factory) -> None:
    async with publish_session_factory() as session:
        session.add_all([_job("job-1"), _job("job-2")])
        await session.commit()

    adapter = FakeAdapter(submit_error=RuntimeError("temporary failure"))
    worker = PublishingWorker(
        session_factory=publish_session_factory,
        adapter_registry={"douyin": adapter},
        batch_size=2,
    )

    assert await worker.run_once() == 2
    first = await _read_job(publish_session_factory, "job-1")
    second = await _read_job(publish_session_factory, "job-2")
    assert first.status == "failed_retryable"
    assert first.error_code == "publish_submit_failed"
    assert second.status == "failed_retryable"
    assert adapter.submit_calls == ["job-1", "job-2"]


async def test_start_and_stop_are_idempotent(publish_session_factory) -> None:
    worker = PublishingWorker(session_factory=publish_session_factory, poll_interval=0.01)

    await worker.start()
    task = worker.task
    await worker.start()
    assert worker.task is task

    await worker.stop()
    assert worker.task is None
    await worker.stop()

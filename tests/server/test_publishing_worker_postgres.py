from __future__ import annotations

import asyncio
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from lib.db.base import utc_now
from lib.db.models.assembly_plan import AssemblyPlan
from lib.db.models.publish import PublishJob
from lib.db.models.render_job import RenderArtifact, RenderJob, RenderReviewSnapshot
from lib.db.models.user import User
from server.services.publishing_worker import PublishingWorker

_PG_DATABASE_URL = os.environ.get("DATABASE_URL", "")
pytestmark = [
    pytest.mark.integration,
    pytest.mark.uses_db,
    pytest.mark.skipif(
        not _PG_DATABASE_URL.startswith("postgresql"),
        reason="publishing PostgreSQL concurrency checks require DATABASE_URL=postgresql+asyncpg://...",
    ),
]


async def _seed_job(session: AsyncSession, *, max_attempts: int = 3) -> tuple[str, str]:
    # Keep fixture identifiers within the varchar(36) IDs used by the persisted media tables.
    suffix = uuid4().hex[:8]
    now = utc_now()
    user_id = f"pg-publish-user-{suffix}"
    plan_id = f"pg-publish-plan-{suffix}"
    render_job_id = f"pg-publish-render-{suffix}"
    artifact_id = f"pg-publish-artifact-{suffix}"
    review_id = f"pg-publish-review-{suffix}"
    publish_id = f"pg-publish-job-{suffix}"

    # Flush each dependency layer explicitly because these models intentionally do not
    # declare ORM relationships; PostgreSQL enforces the migration's foreign keys.
    session.add(User(id=user_id, username=f"pg-publish-{suffix}"))
    await session.flush()
    session.add(
        AssemblyPlan(
            id=plan_id,
            user_id=user_id,
            project_name="pg-publish-test",
            scope="episode",
            name="PostgreSQL publishing test",
            status="draft",
            current_revision_number=1,
            current_source_fingerprint="source-fingerprint",
            created_at=now,
            updated_at=now,
        )
    )
    await session.flush()
    session.add(
        RenderJob(
            id=render_job_id,
            plan_id=plan_id,
            project_name="pg-publish-test",
            user_id=user_id,
            revision_number=1,
            kind="final",
            status="succeeded",
            attempt=1,
            max_attempts=3,
            input_fingerprint="source-fingerprint",
            created_at=now,
            updated_at=now,
            completed_at=now,
        )
    )
    await session.flush()
    session.add(
        RenderArtifact(
            id=artifact_id,
            render_job_id=render_job_id,
            plan_id=plan_id,
            project_name="pg-publish-test",
            user_id=user_id,
            revision_number=1,
            kind="final",
            relative_path="render_artifacts/postgres-publish-test.mp4",
            mime_type="video/mp4",
            size_bytes=1,
            duration_seconds=1.0,
            fingerprint="artifact-fingerprint",
            created_at=now,
        )
    )
    await session.flush()
    session.add(
        RenderReviewSnapshot(
            id=review_id,
            artifact_id=artifact_id,
            plan_id=plan_id,
            project_name="pg-publish-test",
            user_id=user_id,
            revision_number=1,
            source_fingerprint="source-fingerprint",
            artifact_fingerprint="artifact-fingerprint",
            status="ready",
            checks_json="{}",
            created_at=now,
            confirmed_by=user_id,
            confirmed_at=now,
        )
    )
    await session.flush()
    session.add(
        PublishJob(
            id=publish_id,
            user_id=user_id,
            plan_id=plan_id,
            project_name="pg-publish-test",
            artifact_id=artifact_id,
            review_snapshot_id=review_id,
            revision_number=1,
            source_fingerprint="source-fingerprint",
            artifact_fingerprint="artifact-fingerprint",
            platform="test",
            destination_json="{}",
            idempotency_key=f"idempotency-{suffix}",
            request_fingerprint="request-fingerprint",
            status="queued",
            attempt=0,
            max_attempts=max_attempts,
            created_at=now,
            updated_at=now,
        )
    )
    await session.commit()
    return publish_id, user_id


async def _cleanup_job(session: AsyncSession, publish_id: str, user_id: str) -> None:
    job = await session.scalar(select(PublishJob).where(PublishJob.id == publish_id))
    if job is None:
        return
    review_id = job.review_snapshot_id
    artifact_id = job.artifact_id
    render_job_id = await session.scalar(select(RenderArtifact.render_job_id).where(RenderArtifact.id == artifact_id))
    plan_id = job.plan_id
    await session.execute(delete(PublishJob).where(PublishJob.id == publish_id))
    await session.execute(delete(RenderReviewSnapshot).where(RenderReviewSnapshot.id == review_id))
    await session.execute(delete(RenderArtifact).where(RenderArtifact.id == artifact_id))
    if render_job_id is not None:
        await session.execute(delete(RenderJob).where(RenderJob.id == render_job_id))
    await session.execute(delete(AssemblyPlan).where(AssemblyPlan.id == plan_id))
    await session.execute(delete(User).where(User.id == user_id))
    await session.commit()


async def _read_job(factory: async_sessionmaker[AsyncSession], job_id: str) -> PublishJob:
    async with factory() as session:
        job = await session.scalar(select(PublishJob).where(PublishJob.id == job_id))
        assert job is not None
        return job


@pytest.fixture()
async def postgres_session_factories():
    first_engine = create_async_engine(_PG_DATABASE_URL, poolclass=NullPool)
    second_engine = create_async_engine(_PG_DATABASE_URL, poolclass=NullPool)
    first = async_sessionmaker(first_engine, expire_on_commit=False)
    second = async_sessionmaker(second_engine, expire_on_commit=False)
    try:
        yield first, second
    finally:
        await first_engine.dispose()
        await second_engine.dispose()


async def test_postgres_workers_atomically_claim_one_job(postgres_session_factories) -> None:
    first_factory, second_factory = postgres_session_factories
    async with first_factory() as session:
        job_id, user_id = await _seed_job(session)

    try:
        first = PublishingWorker(session_factory=first_factory, worker_id="pg-worker-1")
        second = PublishingWorker(session_factory=second_factory, worker_id="pg-worker-2")
        claimed = await asyncio.gather(first._claim_job("new"), second._claim_job("new"))

        assert sum(job is not None for job in claimed) == 1
        stored = await _read_job(first_factory, job_id)
        assert stored.status == "publishing"
        assert stored.attempt == 1
        assert stored.worker_id in {"pg-worker-1", "pg-worker-2"}
        assert stored.lease_until is not None
    finally:
        async with first_factory() as session:
            await _cleanup_job(session, job_id, user_id)


async def test_postgres_expired_lease_recovers_once_and_respects_attempt_limit(postgres_session_factories) -> None:
    first_factory, second_factory = postgres_session_factories
    async with first_factory() as session:
        job_id, user_id = await _seed_job(session, max_attempts=3)

    try:
        first = PublishingWorker(session_factory=first_factory, worker_id="pg-worker-1")
        second = PublishingWorker(session_factory=second_factory, worker_id="pg-worker-2")
        assert await first._claim_job("new") is not None

        async with first_factory() as session:
            await session.execute(
                # The worker crashed after committing its lease; the next worker must recover it.
                update(PublishJob).where(PublishJob.id == job_id).values(lease_until=utc_now() - timedelta(seconds=1))
            )
            await session.commit()

        recovered = await second._claim_job("due")
        assert recovered is not None
        assert recovered.attempt == 2

        async with first_factory() as session:
            await session.execute(
                update(PublishJob).where(PublishJob.id == job_id).values(lease_until=utc_now() - timedelta(seconds=1))
            )
            await session.commit()

        recovered_again = await first._claim_job("due")
        assert recovered_again is not None
        assert recovered_again.attempt == 3

        async with first_factory() as session:
            await session.execute(
                update(PublishJob).where(PublishJob.id == job_id).values(lease_until=utc_now() - timedelta(seconds=1))
            )
            await session.commit()

        assert await second._claim_job("due") is None
        stored = await _read_job(first_factory, job_id)
        assert stored.attempt == stored.max_attempts == 3
    finally:
        async with first_factory() as session:
            await _cleanup_job(session, job_id, user_id)

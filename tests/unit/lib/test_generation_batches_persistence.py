"""Persistence and transaction tests for durable generation batches."""

from __future__ import annotations

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.db.base import Base
from lib.db.models.generation_batch import GenerationBatchRecord
from lib.db.models.task import Task
from lib.db.models.user import User
from lib.db.repositories.generation_batch_repo import GenerationBatchRepository
from lib.generation_batches import (
    BatchAdmissionError,
    BatchOrchestrator,
    GenerationBatchItem,
    GenerationBatchRequest,
)
from lib.generation_queue import GenerationQueue

pytestmark = pytest.mark.unit


@pytest.fixture
async def durable_queue():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        session.add_all(
            [
                User(id="owner", username="owner"),
                User(id="other", username="other"),
            ]
        )
        await session.commit()
    yield factory, GenerationQueue(session_factory=factory)
    await engine.dispose()


def _request(*resource_ids: str) -> GenerationBatchRequest:
    return GenerationBatchRequest(
        project_name="demo",
        items=tuple(
            GenerationBatchItem(
                item_id=f"item-{resource_id}",
                task={
                    "task_type": "storyboard",
                    "media_type": "image",
                    "resource_id": resource_id,
                    "payload": {"prompt": f"prompt for {resource_id}"},
                    "script_file": "episode_1.json",
                    "provider_id": "test-provider",
                    "user_id": "other",
                },
            )
            for resource_id in resource_ids
        ),
    )


async def _orchestrator(factory, queue, *, user_id: str = "owner", project_name: str = "demo"):
    session = factory()
    return session, BatchOrchestrator(
        repository=GenerationBatchRepository(session, user_id=user_id, project_name=project_name),
        tasks=queue.batch_adapter(project_name=project_name),
        user_id=user_id,
    )


async def test_admission_persists_batch_and_tasks_with_server_owner(durable_queue) -> None:
    factory, queue = durable_queue
    session, orchestrator = await _orchestrator(factory, queue)
    try:
        batch = await orchestrator.admit(_request("one", "two"))
    finally:
        await session.close()

    async with factory() as verify:
        stored = await GenerationBatchRepository(verify, user_id="owner", project_name="demo").get(batch.batch_id)
        task_rows = (await verify.execute(select(Task).order_by(Task.resource_id))).scalars().all()

    assert stored is not None
    assert stored.task_ids == batch.task_ids
    assert [row.resource_id for row in task_rows] == ["one", "two"]
    assert {row.user_id for row in task_rows} == {"owner"}
    assert all(row.task_id in stored.task_ids for row in task_rows)


async def test_admission_conflict_rolls_back_batch_and_every_new_task(durable_queue) -> None:
    factory, queue = durable_queue
    await queue.enqueue_task(
        project_name="demo",
        task_type="storyboard",
        media_type="image",
        resource_id="existing",
        script_file="episode_1.json",
        payload={"prompt": "prompt for existing"},
        provider_id="test-provider",
        user_id="owner",
    )
    session, orchestrator = await _orchestrator(factory, queue)
    try:
        with pytest.raises(BatchAdmissionError):
            await orchestrator.admit(_request("new", "existing"))
    finally:
        await session.close()

    async with factory() as verify:
        batch_count = await verify.scalar(select(func.count()).select_from(GenerationBatchRecord))
        tasks = (await verify.execute(select(Task).order_by(Task.resource_id))).scalars().all()

    assert batch_count == 0
    assert [task.resource_id for task in tasks] == ["existing"]


async def test_retry_replaces_only_failed_task_and_persists_mapping(durable_queue) -> None:
    factory, queue = durable_queue
    session, orchestrator = await _orchestrator(factory, queue)
    try:
        batch = await orchestrator.admit(_request("one", "two"))
        first = await queue.claim_next_task("image")
        assert first is not None
        await queue.mark_task_failed(first["task_id"], "provider failed")

        retried = await orchestrator.retry_failed(batch.batch_id)
    finally:
        await session.close()

    assert retried.task_ids[0] != batch.task_ids[0]
    assert retried.task_ids[1] == batch.task_ids[1]
    async with factory() as verify:
        stored = await GenerationBatchRepository(verify, user_id="owner", project_name="demo").get(batch.batch_id)
        task_rows = (await verify.execute(select(Task))).scalars().all()
    assert stored is not None
    assert stored.task_ids == retried.task_ids
    assert len(task_rows) == 3


async def test_repository_hides_batches_from_other_user_or_project(durable_queue) -> None:
    factory, queue = durable_queue
    session, orchestrator = await _orchestrator(factory, queue)
    try:
        batch = await orchestrator.admit(_request("one"))
    finally:
        await session.close()

    async with factory() as verify:
        assert await GenerationBatchRepository(verify, user_id="other", project_name="demo").get(batch.batch_id) is None
        assert (
            await GenerationBatchRepository(verify, user_id="owner", project_name="other-project").get(batch.batch_id)
            is None
        )

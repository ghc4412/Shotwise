"""Production GenerationQueue adapter tests for durable batch admission."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from lib.db.base import Base
from lib.generation_batches import (
    BatchAdmissionError,
    BatchOrchestrator,
    BatchStatus,
    GenerationBatchItem,
    GenerationBatchRequest,
    InMemoryGenerationBatchRepository,
)
from lib.generation_queue import GenerationQueue

pytestmark = pytest.mark.unit


@pytest.fixture
async def queue():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    yield GenerationQueue(session_factory=factory)
    await engine.dispose()


def _task(resource_id: str) -> dict[str, object]:
    return {
        "task_type": "storyboard",
        "media_type": "image",
        "resource_id": resource_id,
        "provider_id": "test-provider",
    }


def _request() -> GenerationBatchRequest:
    return GenerationBatchRequest(
        project_name="demo",
        items=(
            GenerationBatchItem(item_id="first", task=_task("first")),
            GenerationBatchItem(item_id="second", task=_task("second")),
        ),
    )


async def test_batch_adapter_admits_all_tasks_in_one_operation(queue) -> None:
    adapter = queue.batch_adapter(project_name="demo")

    task_ids = await adapter.admit_all((_task("first"), _task("second")))

    assert len(task_ids) == 2
    admitted = [await queue.get_task(task_id) for task_id in task_ids]
    assert all(task is not None and task["status"] == "queued" for task in admitted)
    assert admitted[0]["prompt_preview"]["source"] == "enqueue_snapshot"


async def test_batch_adapter_rolls_back_every_insert_when_one_item_conflicts(queue) -> None:
    existing = await queue.enqueue_task(
        project_name="demo",
        task_type="storyboard",
        media_type="image",
        resource_id="existing",
        provider_id="test-provider",
    )
    adapter = queue.batch_adapter(project_name="demo")

    with pytest.raises(BatchAdmissionError):
        await adapter.admit_all((_task("new"), _task("existing")))

    assert await queue.get_task(existing["task_id"]) is not None
    tasks = await queue.list_tasks(project_name="demo")
    assert [task["resource_id"] for task in tasks["items"]] == ["existing"]


async def test_batch_adapter_supports_partial_success_and_retrying_only_failed_items(queue) -> None:
    adapter = queue.batch_adapter(project_name="demo")
    orchestrator = BatchOrchestrator(repository=InMemoryGenerationBatchRepository(), tasks=adapter)
    batch = await orchestrator.admit(_request())

    running = await queue.claim_next_task("image")
    assert running is not None
    await queue.mark_task_failed(running["task_id"], "provider failed")

    retried = await orchestrator.retry_failed(batch.batch_id)

    assert retried.task_ids[0] != batch.task_ids[0]
    assert retried.task_ids[1] == batch.task_ids[1]
    assert (await queue.get_task(retried.task_ids[0]))["status"] == "queued"
    assert await orchestrator.get_status(batch.batch_id) is BatchStatus.RUNNING


async def test_batch_cancel_cancels_all_active_tasks_and_reports_partial_success(queue) -> None:
    adapter = queue.batch_adapter(project_name="demo")
    orchestrator = BatchOrchestrator(repository=InMemoryGenerationBatchRepository(), tasks=adapter)
    batch = await orchestrator.admit(_request())

    running = await queue.claim_next_task("image")
    assert running is not None
    await queue.mark_task_succeeded(running["task_id"], {"file_path": "out.png"})

    status = await orchestrator.cancel(batch.batch_id)

    assert status is BatchStatus.PARTIALLY_SUCCEEDED
    assert (await queue.get_task(batch.task_ids[1]))["status"] == "cancelled"
